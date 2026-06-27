"""Clock, ProtectedPerson, and Fiduciary routes."""

from flask import Blueprint

from clock import clock, parse_iso
from db import db, stamp_create
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_enum,
    require_int,
    parse_pagination,
    paginate,
)

bp = Blueprint("reference", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10). Outside the /gc mount.
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_identity()
    require_role(role, ["CourtClerk"])
    body = get_json_body()
    to_iso = require_string(body, "to_iso8601")
    try:
        parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO-8601 instant")
    now_iso = clock.set(to_iso)
    return object_response({"now_iso": now_iso}, 200)


# ---------------------------------------------------------------------------
# ProtectedPerson
# ---------------------------------------------------------------------------
@bp.route("/gc/protected-persons", methods=["POST"])
def create_person():
    _, role = get_identity()
    require_role(role, ["Petitioner", "CourtClerk"])
    body = get_json_body()
    full_name = require_string(body, "full_name")
    dob = require_string(body, "date_of_birth")
    annual_income = require_int(body, "annual_income_cents", minimum=0)
    liquid_estate = require_int(body, "liquid_estate_cents", minimum=0)
    record = {
        "full_name": full_name,
        "date_of_birth": dob,
        "annual_income_cents": annual_income,
        "liquid_estate_cents": liquid_estate,
        "capacity_status": "PRESUMED_COMPETENT",
        "active_case_id": None,
    }
    stamp_create(record)
    with db.lock:
        db.protected_persons[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/protected-persons/<pid>", methods=["GET"])
def get_person(pid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    if pid not in db.protected_persons:
        raise err("ERR_NOT_FOUND", "Protected person not found")
    return object_response(db.protected_persons[pid], 200)


@bp.route("/gc/protected-persons", methods=["GET"])
def list_persons():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items, total = paginate(list(db.protected_persons.values()), limit, offset)
    return array_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Fiduciary
# ---------------------------------------------------------------------------
@bp.route("/gc/fiduciaries", methods=["POST"])
def create_fiduciary():
    _, role = get_identity()
    require_role(role, ["CourtClerk", "Petitioner"])
    body = get_json_body()
    full_name = require_string(body, "full_name")
    kind = require_enum(body, "fiduciary_kind", {"FAMILY", "PROFESSIONAL", "PUBLIC_AGENCY"})
    record = {
        "full_name": full_name,
        "fiduciary_kind": kind,
        "is_disqualified": False,
        "open_appointment_count": 0,
    }
    stamp_create(record)
    with db.lock:
        db.fiduciaries[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/fiduciaries/<fid>", methods=["GET"])
def get_fiduciary(fid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    if fid not in db.fiduciaries:
        raise err("ERR_NOT_FOUND", "Fiduciary not found")
    return object_response(db.fiduciaries[fid], 200)


@bp.route("/gc/fiduciaries", methods=["GET"])
def list_fiduciaries():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items, total = paginate(list(db.fiduciaries.values()), limit, offset)
    return array_response(items, limit, offset, total)
