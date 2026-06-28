"""Clients (PRD §3.1)."""
from flask import Blueprint

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = h.get_body()
    full_name = h.require_str(body, "full_name")
    email = h.require_str(body, "email")
    billing_tier = h.optional_enum(body, "billing_tier", h.BILLING_TIERS, "RESIDENTIAL")
    # email unique across clients (PRD §3.1) — treated as a body well-formedness
    # constraint (ERR_INVALID_REQUEST).
    for c in db.clients.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across clients")
    entity = {
        "full_name": full_name,
        "email": email,
        "billing_tier": billing_tier,
    }
    db.stamp_create(entity)
    db.clients[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/clients/<client_id>")
def get_client(client_id):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "Client"})
    entity = h.get_or_404(db.clients, client_id)
    return success(h.public(entity))
