"""Client registration and fetch (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE, ERR_NOT_FOUND
from middleware import require_auth, ROLE_ANONYMOUS, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object
from routes._helpers import get_body, require_str, serialize
from services.common import stamp_create

bp = Blueprint("clients", __name__)


@bp.post("/studio/clients")
def create_client():
    # Anonymous self-registration or StudioAdmin on behalf.
    require_auth([ROLE_ANONYMOUS, ROLE_STUDIO_ADMIN])
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")

    # Email unique across clients (PRD §3.1).
    for c in db.clients.values():
        if c["email"] == email:
            raise APIError(ERR_DUPLICATE_RESOURCE, 409, "Client email already exists")

    client = {
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "status": "ACTIVE",
    }
    stamp_create(client)
    db.clients[client["id"]] = client
    return ok_object(serialize(client), 201)


@bp.get("/studio/clients/<id>")
def get_client(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    client = db.clients.get(id)
    if client is None:
        raise APIError(ERR_NOT_FOUND, 404, "Client not found")
    return ok_object(serialize(client), 200)
