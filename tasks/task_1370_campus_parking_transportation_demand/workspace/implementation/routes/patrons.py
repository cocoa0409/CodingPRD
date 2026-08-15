"""Patron endpoints."""
from flask import Blueprint, request

import db
from errors import bad_request, not_found, ERR_PATRON_NOT_FOUND
from middleware import get_caller, require_roles, ALL_ROLES
from response import success, success_list, parse_pagination
from services.core import new_record, serialize

bp = Blueprint("patrons", __name__)

CAMPUS_ROLES = ("STUDENT", "STAFF", "FACULTY")
RESIDENCIES = ("ON_CAMPUS", "OFF_CAMPUS")
COMMUTE_MODES = ("DRIVE_ALONE", "CARPOOL", "TRANSIT", "BIKE", "WALK")


@bp.post("/parking/patrons")
def create_patron():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    full_name = body.get("full_name")
    campus_role = body.get("campus_role")
    residency = body.get("residency")
    commute = body.get("primary_commute_mode")

    if not isinstance(full_name, str) or not full_name:
        raise bad_request("full_name is required")
    if campus_role not in CAMPUS_ROLES:
        raise bad_request("campus_role must be one of STUDENT, STAFF, FACULTY")
    if residency not in RESIDENCIES:
        raise bad_request("residency must be ON_CAMPUS or OFF_CAMPUS")
    if commute not in COMMUTE_MODES:
        raise bad_request("primary_commute_mode must be one of DRIVE_ALONE, CARPOOL, TRANSIT, BIKE, WALK")

    record = new_record()
    record.update(
        full_name=full_name,
        campus_role=campus_role,
        residency=residency,
        primary_commute_mode=commute,
        outstanding_balance_cents=0,
        standing="GOOD_STANDING",
    )
    db.patrons[record["id"]] = record
    return success(serialize(record), 201)


@bp.get("/parking/patrons")
def list_patrons():
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)

    role_filter = request.args.get("campus_role")
    residency_filter = request.args.get("residency")
    standing_filter = request.args.get("standing")

    items = list(db.patrons.values())
    if role_filter is not None:
        items = [p for p in items if p["campus_role"] == role_filter]
    if residency_filter is not None:
        items = [p for p in items if p["residency"] == residency_filter]
    if standing_filter is not None:
        items = [p for p in items if p["standing"] == standing_filter]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([serialize(p) for p in page], limit, offset, total)


@bp.get("/parking/patrons/<patronId>")
def get_patron(patronId):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    record = db.patrons.get(patronId)
    if record is None:
        raise not_found(ERR_PATRON_NOT_FOUND, "No patron with the given id")
    return success(serialize(record), 200)
