"""Client endpoints."""

from flask import Blueprint

import db
from middleware import auth
from response import ok_object
from services.core import get_or_404, list_response, new_record, pub
from util import body, v_str

bp = Blueprint("clients", __name__)


@bp.post("/fca/clients")
def create_client():
    auth("Consultant")
    data = body()
    name = v_str(data, "name")
    contact_email = v_str(data, "contact_email")
    rec = new_record()
    rec.update({"name": name, "contact_email": contact_email})
    db.clients[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/fca/clients")
def list_clients():
    auth()
    return list_response(list(db.clients.values()))


@bp.get("/fca/clients/<client_id>")
def get_client(client_id):
    auth()
    return ok_object(pub(get_or_404(db.clients, client_id, "Client")))
