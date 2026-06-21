"""CuteAllocation routes: allocate, fetch, list, release."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success
from services import occupancy

bp = Blueprint("cute_allocations", __name__)

READ_ROLES = {"OpsAdmin", "RampAgent"}


@bp.route("/cute-allocations", methods=["POST"])
def create_allocation():
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    body = helpers.get_body()

    # existence (priority 3): flight_id then cute_unit_id (declaration order)
    flight = None
    if body.get("flight_id") is not None:
        flight = db.flights.get(body["flight_id"])
        if flight is None:
            raise errors.not_found("Flight not found.")
    cute = None
    if body.get("cute_unit_id") is not None:
        cute = db.cute_units.get(body["cute_unit_id"])
        if cute is None:
            raise errors.not_found("CUTE unit not found.")

    # well-formedness (priority 4)
    helpers.require_fields(body, ["flight_id", "cute_unit_id", "start_utc", "end_utc"])
    start_dt, start_raw = helpers.parse_dt(body["start_utc"], "start_utc")
    end_dt, end_raw = helpers.parse_dt(body["end_utc"], "end_utc")
    if end_dt <= start_dt:
        raise errors.invalid_request("end_utc must be strictly later than start_utc.")

    # CUTE double-book (priority 9)
    if occupancy.cute_conflicts(body["cute_unit_id"], start_dt, end_dt):
        raise errors.cute_busy()

    rec = {
        "id": db.new_id(),
        "flight_id": flight["id"],
        "cute_unit_id": cute["id"],
        "start_utc": start_raw,
        "end_utc": end_raw,
        "status": "HELD",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_create(rec)
    db.cute_allocations[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/cute-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.cute_allocations.get(aid)
    if rec is None:
        raise errors.not_found("CUTE allocation not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/cute-allocations", methods=["GET"])
def list_allocations():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    flight_id = request.args.get("flight_id")
    cute_unit_id = request.args.get("cute_unit_id")
    status = request.args.get("status")
    recs = list(db.cute_allocations.values())
    if flight_id is not None:
        recs = [r for r in recs if r.get("flight_id") == flight_id]
    if cute_unit_id is not None:
        recs = [r for r in recs if r.get("cute_unit_id") == cute_unit_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


@bp.route("/cute-allocations/<aid>/release", methods=["POST"])
def release(aid):
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    rec = db.cute_allocations.get(aid)
    if rec is None:
        raise errors.not_found("CUTE allocation not found.")
    if rec["status"] != "HELD":
        raise errors.invalid_state("Allocation is not HELD.")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return success(helpers.serialize(rec), status=200)
