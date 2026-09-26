# Recibe el formulario de la landing y guarda a la clienta en systeme.io con etiquetas.
# La clave va en Vercel → Settings → Environment Variables → SYSTEME_API_KEY (nunca en el código).
# Para pasarte a GoHighLevel más adelante solo se cambia este archivo; la página no se toca.
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

API = os.environ.get("SYSTEME_API_BASE", "https://api.systeme.io/api")
# etiquetas que se reemplazan si la clienta vuelve a llenar el formulario (las de servicio se acumulan)
REEMPLAZABLES = ("Cuándo - ", "Horario - ")


def llamar(metodo, ruta, datos=None, tipo="application/json"):
    cuerpo = None if datos is None else json.dumps(datos).encode()
    req = urllib.request.Request(API + ruta, data=cuerpo, method=metodo, headers={
        "X-API-Key": os.environ["SYSTEME_API_KEY"], "Content-Type": tipo, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            texto = r.read()
            return r.status, json.loads(texto) if texto else None
    except urllib.error.HTTPError as e:
        texto = e.read()
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, None


def id_etiqueta(nombre):
    _, r = llamar("GET", "/tags?" + urllib.parse.urlencode({"query": nombre, "limit": 100}))
    for t in (r or {}).get("items", []):
        if t["name"].lower() == nombre.lower():
            return t["id"]
    estado, t = llamar("POST", "/tags", {"name": nombre})
    if estado == 201:
        return t["id"]
    raise RuntimeError(f"no se pudo crear la etiqueta {nombre!r}: {estado} {t}")


def texto(d, clave, largo=100):
    return str(d.get(clave) or "").strip()[:largo]


def guardar(d):
    email = texto(d, "email", 150).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", email):
        raise ValueError("correo inválido")
    curiosa = bool(d.get("curiosa"))
    campos = [{"slug": "first_name", "value": texto(d, "nombre")},
              {"slug": "phone_number", "value": texto(d, "telefono", 30)}]

    # si ya existe (volvió a llenar el formulario), se actualiza en vez de duplicarla
    _, r = llamar("GET", "/contacts?" + urllib.parse.urlencode({"email": email, "limit": 10}))
    existentes = (r or {}).get("items", [])
    if existentes:
        contacto = existentes[0]
        llamar("PATCH", f"/contacts/{contacto['id']}", {"fields": campos}, "application/merge-patch+json")
    else:
        estado, contacto = llamar("POST", "/contacts", {"email": email, "locale": "es", "fields": campos})
        if estado != 201:
            raise RuntimeError(f"no se pudo crear el contacto: {estado} {contacto}")

    horario = texto(d, "horario").split(" (")[0]
    etiquetas = ["Landing MK", "Curiosa" if curiosa else "Descuento MK10",
                 "Categoría - " + texto(d, "categoria"), "Servicio - " + texto(d, "servicio"),
                 "Cuándo - " + texto(d, "cuando")] + (["Horario - " + horario] if horario else [])

    actuales = {t["name"]: t["id"] for t in contacto.get("tags", [])}
    for nombre, tag_id in actuales.items():
        viejo = nombre.startswith(REEMPLAZABLES) and nombre not in etiquetas
        if viejo or (nombre == "Curiosa" and not curiosa):  # si ya pidió el descuento, deja de ser curiosa
            llamar("DELETE", f"/contacts/{contacto['id']}/tags/{tag_id}")
    for nombre in etiquetas:
        if nombre not in actuales:
            llamar("POST", f"/contacts/{contacto['id']}/tags", {"tagId": id_etiqueta(nombre)})


class handler(BaseHTTPRequestHandler):
    def responder(self, estado, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode()
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    # abrir tudominio.com/api/lead en el navegador sirve para revisar que la clave esté puesta
    def do_GET(self):
        self.responder(200, {"funciona": True, "clave_systeme_configurada": bool(os.environ.get("SYSTEME_API_KEY"))})

    def do_POST(self):
        if not os.environ.get("SYSTEME_API_KEY"):
            return self.responder(500, {"error": "Falta SYSTEME_API_KEY en Vercel"})
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            try:
                datos = json.loads(self.rfile.read(largo) or b"{}")
            except ValueError:
                raise ValueError("datos del formulario inválidos")
            guardar(datos)
            self.responder(200, {"ok": True})
        except ValueError as e:
            self.responder(400, {"error": str(e)})
        except Exception as e:
            print("Error guardando en systeme.io:", e)  # aparece en Vercel → Logs
            self.responder(502, {"error": "No se pudo guardar el contacto"})
