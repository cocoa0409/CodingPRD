"""Vendor registration (PRD §3.1)."""
from flask import Blueprint

import db
from db import store
from middleware import authenticate, require_roles
from response import created
from validation import get_body, validate_schema

bp = Blueprint("vendors", __name__)

VENDOR_SCHEMA = {
    "name": ("string", True, None),
    "trade": ("enum", True, ["REPAIR", "PAINT", "CARPET", "CLEAN"]),
}


@bp.post("/make-ready/vendors")
def create_vendor():
    authenticate()
    require_roles(["PropertyManager"])
    body = get_body()
    validate_schema(body, VENDOR_SCHEMA)
    vendor = {
        "id": db.new_id(),
        "name": body["name"],
        "trade": body["trade"],
        "open_assignment_count": 0,
    }
    db.new_common(vendor)
    store.vendors[vendor["id"]] = vendor
    return created(vendor)
