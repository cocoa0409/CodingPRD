"""Property endpoints."""

from flask import Blueprint

import db
from errors import ERR_PROPERTY_NOT_FOUND
from middleware import PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from util import get_json_body, serialize, validate_body

bp = Blueprint("properties", __name__)

CREATE_SPEC = {
    "owner_user_id": ("string", True, None),
    "address_line": ("string", True, None),
    "state_code": ("string", True, None),
    "has_existing_shaft": ("bool", False, None),
}


@bp.post("/api/properties")
@require_roles(PROJECT_COORDINATOR)
def create_property():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    rec = db.new_record({
        "owner_user_id": vals["owner_user_id"],
        "address_line": vals["address_line"],
        "state_code": vals["state_code"],
        "has_existing_shaft": vals.get("has_existing_shaft", False),
    })
    db.properties[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/properties")
@require_roles(*ALL_ROLES)
def list_properties():
    return list_endpoint(db.properties, {"owner_user_id": "owner_user_id", "state_code": "state_code"})


@bp.get("/api/properties/<propertyId>")
@require_roles(*ALL_ROLES)
def get_property(propertyId):
    rec = get_or_404(db.properties, propertyId, ERR_PROPERTY_NOT_FOUND, "Property")
    return ok(serialize(rec))
