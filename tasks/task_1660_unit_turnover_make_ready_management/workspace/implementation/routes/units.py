"""Unit endpoints, move-in, and the per-unit commitment listing (PRD §3.1, §3.8)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import authenticate, require_roles
from response import created, ok, paged
from services import commitments_of_unit
from validation import get_body, validate_schema

bp = Blueprint("units", __name__)

UNIT_SCHEMA = {
    "property_id": ("string", True, None),
    "unit_number": ("string", True, None),
    "square_feet": ("integer", True, None),
}

READ_ROLES = ["RegionalManager", "PropertyManager", "TurnCoordinator",
              "Inspector"]


@bp.post("/make-ready/units")
def create_unit():
    authenticate()
    require_roles(["PropertyManager"])
    body = get_body()
    validate_schema(body, UNIT_SCHEMA)
    prop = store.properties.get(body["property_id"])
    if prop is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Property not found")
    unit = {
        "id": db.new_id(),
        "property_id": body["property_id"],
        "unit_number": body["unit_number"],
        "square_feet": body["square_feet"],
        "status": "OCCUPIED",
    }
    db.new_common(unit)
    store.units[unit["id"]] = unit
    return created(unit)


@bp.get("/make-ready/units/<unit_id>")
def get_unit(unit_id):
    authenticate()
    require_roles(READ_ROLES)
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Unit not found")
    return ok(unit)


@bp.get("/make-ready/units")
def list_units():
    authenticate()
    require_roles(READ_ROLES)
    page, pg = paged(list(store.units.values()), ("property_id", "status"))
    return ok(page, rtype="array", pagination=pg)


@bp.post("/make-ready/units/<unit_id>/record-move-in")
def record_move_in(unit_id):
    authenticate()
    require_roles(["TurnCoordinator"])
    body = get_body()
    validate_schema(body, {"move_in_date": ("date", True, None)})
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Unit not found")
    if unit["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Unit must be READY to record a move-in")
    move_in = db.parse_date(body["move_in_date"])
    unit["status"] = "OCCUPIED"
    db.touch(unit)
    # Resolve any open commitment in the same step (PRD §3.8).
    for c in commitments_of_unit(unit_id):
        if c["status"] not in ("ACTIVE", "AT_RISK"):
            continue
        committed = db.parse_date(c["committed_delivery_date"])
        c["status"] = "FULFILLED" if move_in <= committed else "BREACHED"
        db.touch(c)
    return ok(unit)


@bp.get("/make-ready/units/<unit_id>/lease-commitments")
def list_unit_lease_commitments(unit_id):
    authenticate()
    require_roles(["RegionalManager", "PropertyManager", "TurnCoordinator"])
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Unit not found")
    page, pg = paged(commitments_of_unit(unit_id))
    return ok(page, rtype="array", pagination=pg)
