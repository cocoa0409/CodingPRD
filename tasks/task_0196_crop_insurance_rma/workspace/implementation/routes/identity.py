"""Producer and Agent registration (PRD §3.2)."""
from flask import Blueprint

import db
import response
from middleware import authenticate, require_role, get_json
from services.common import make_identity_common, public, as_string, as_enum

bp = Blueprint("identity", __name__)


@bp.post("/producers")
def create_producer():
    # POST /producers — RmaAdmin, Agent (PRD §4)
    _, role = authenticate()
    require_role(role, {"RmaAdmin", "Agent"})
    body = get_json()
    name = as_string(body, "name")
    tax_id = as_string(body, "tax_id")
    entity = make_identity_common()
    entity.update({"name": name, "tax_id": tax_id})
    db.producers[entity["id"]] = entity
    return response.success_object(public(entity), 201)


@bp.post("/agents")
def create_agent():
    # POST /agents — RmaAdmin only (PRD §4)
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    body = get_json()
    name = as_string(body, "name")
    license_number = as_string(body, "license_number")
    role_kind = as_enum(body, "role_kind", {"SELLING", "ADJUSTING"})
    entity = make_identity_common()
    entity.update({
        "name": name,
        "license_number": license_number,
        "role_kind": role_kind,
    })
    db.agents[entity["id"]] = entity
    return response.success_object(public(entity), 201)
