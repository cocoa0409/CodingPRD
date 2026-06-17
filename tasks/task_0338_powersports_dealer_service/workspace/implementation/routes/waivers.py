"""Test-ride waivers (PRD 3.11)."""

from flask import Blueprint, request

import errors
from common import get_body, stamp_new, serialize, touch, paginate, as_str
from db import db, parse_iso
from lookups import get_waiver, get_customer, get_unit
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("waivers", __name__)


@bp.route("/test-ride-waivers", methods=["POST"])
def create_waiver():
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    body = get_body()
    customer_id = as_str(body, "customer_id")
    get_customer(customer_id)
    unit_id = as_str(body, "unit_id")
    get_unit(unit_id)
    signed_at = as_str(body, "signed_at")
    valid_until = as_str(body, "valid_until")
    signed_dt = parse_iso(signed_at)
    valid_dt = parse_iso(valid_until)
    if signed_dt is None or valid_dt is None:
        errors.err(errors.ERR_INVALID_REQUEST, "signed_at/valid_until must be valid timestamps")
    if not (valid_dt > signed_dt):
        errors.err(errors.ERR_INVALID_REQUEST, "valid_until must be after signed_at")

    rec = stamp_new({
        "customer_id": customer_id,
        "unit_id": unit_id,
        "signed_at": signed_at,
        "valid_until": valid_until,
        "status": "SIGNED",
    })
    db.test_ride_waivers[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/test-ride-waivers", methods=["GET"])
def list_waivers():
    _, role = get_user_context()
    require_role(role, {"SalesManager", "DealerPrincipal"})
    f = request.args
    records = []
    for w in db.test_ride_waivers.values():
        if f.get("customer_id") is not None and w["customer_id"] != f.get("customer_id"):
            continue
        if f.get("unit_id") is not None and w["unit_id"] != f.get("unit_id"):
            continue
        if f.get("status") is not None and w["status"] != f.get("status"):
            continue
        records.append(w)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/test-ride-waivers/<wid>", methods=["GET"])
def get_waiver_route(wid):
    _, role = get_user_context()
    require_role(role, {"SalesManager", "DealerPrincipal"})
    rec = get_waiver(wid)
    return ok(serialize(rec), 200)


@bp.route("/test-ride-waivers/<wid>/log-ride", methods=["POST"])
def log_ride(wid):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    waiver = get_waiver(wid)

    # Safety: a ride may not be logged without a SIGNED unexpired waiver.
    if waiver["status"] != "SIGNED":
        errors.err(errors.ERR_WAIVER_REQUIRED, "No SIGNED waiver for this customer/unit")

    valid_dt = parse_iso(waiver["valid_until"])
    # Expiry: at or after valid_until -> mark EXPIRED and reject.
    if db.clock >= valid_dt:
        waiver["status"] = "EXPIRED"
        touch(waiver)
        errors.err(errors.ERR_WAIVER_EXPIRED, "Waiver has expired")

    # Unit must be rideable (IN_STOCK or ON_HOLD).
    unit = db.units.get(waiver["unit_id"])
    if unit is None or unit["status"] not in ("IN_STOCK", "ON_HOLD"):
        errors.err(errors.ERR_UNIT_NOT_RIDEABLE, "Unit is not rideable")

    waiver["status"] = "RIDE_LOGGED"
    touch(waiver)
    return ok(serialize(waiver), 200)


@bp.route("/test-ride-waivers/<wid>/void", methods=["POST"])
def void_waiver(wid):
    _, role = get_user_context()
    require_role(role, {"SalesManager"})
    waiver = get_waiver(wid)
    if waiver["status"] != "SIGNED":
        errors.err(errors.ERR_INVALID_STATE, "Waiver is not SIGNED")
    waiver["status"] = "VOID"
    touch(waiver)
    return ok(serialize(waiver), 200)
