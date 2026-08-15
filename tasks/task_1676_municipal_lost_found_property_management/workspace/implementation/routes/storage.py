"""Storage locations and venues (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_LOCATION_NOT_EMPTY
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from validate import (
    get_body, req_str, req_int, req_bool, require_path, require_ref,
    pagination_params, opt_query_bool, opt_query_str, paginate,
)

bp = Blueprint("storage", __name__)

ADMIN = {"ProgramAdmin"}


# ---------------------------------------------------------------------------
# Storage locations
# ---------------------------------------------------------------------------

@bp.post("/storage-locations")
def create_location():
    body = get_body()
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    capacity_slots = req_int(body, "capacity_slots", minimum=1)
    supports_high_value = req_bool(body, "supports_high_value")
    authorized(ADMIN)
    require_ref("programs", program_id, "program_id")
    rec = core.new_record("storage_locations", {
        "program_id": program_id,
        "name": name,
        "capacity_slots": capacity_slots,
        "supports_high_value": supports_high_value,
        "active": True,
    })
    return success_object(core.serialize_location(rec), 201)


@bp.get("/storage-locations")
def list_locations():
    limit, offset = pagination_params()
    program_id = opt_query_str("program_id")
    active = opt_query_bool("active")
    authorized(STAFF_ROLES)
    recs = list(db["storage_locations"].values())
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if active is not None:
        recs = [r for r in recs if r["active"] == active]
    page, total = paginate(recs, limit, offset)
    return success_list([core.serialize_location(r) for r in page], total, limit, offset)


@bp.get("/storage-locations/<location_id>")
def get_location(location_id):
    authorized(STAFF_ROLES)
    rec = require_path("storage_locations", location_id)
    return success_object(core.serialize_location(rec))


@bp.post("/storage-locations/<location_id>/deactivate")
def deactivate_location(location_id):
    authorized(ADMIN)
    rec = require_path("storage_locations", location_id)
    if core.occupied_slots(location_id) != 0:
        raise_error(ERR_LOCATION_NOT_EMPTY, "storage location has occupied slots")
    rec["active"] = False
    core.touch(rec)
    return success_object(core.serialize_location(rec))


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------

@bp.post("/venues")
def create_venue():
    body = get_body()
    program_id = req_str(body, "program_id")
    name = req_str(body, "name")
    address = req_str(body, "address")
    insurance_cap_cents = req_int(body, "insurance_cap_cents", minimum=0)
    authorized(ADMIN)
    require_ref("programs", program_id, "program_id")
    rec = core.new_record("venues", {
        "program_id": program_id,
        "name": name,
        "address": address,
        "insurance_cap_cents": insurance_cap_cents,
    })
    return success_object(rec, 201)


@bp.get("/venues")
def list_venues():
    limit, offset = pagination_params()
    program_id = opt_query_str("program_id")
    authorized(STAFF_ROLES)
    recs = list(db["venues"].values())
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    authorized(STAFF_ROLES)
    rec = require_path("venues", venue_id)
    return success_object(rec)
