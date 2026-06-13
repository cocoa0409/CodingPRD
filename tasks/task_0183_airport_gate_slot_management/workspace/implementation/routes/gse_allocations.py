"""GseAllocation routes: allocate, fetch, list, release."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success
from services import occupancy

bp = Blueprint("gse_allocations", __name__)

READ_ROLES = {"OpsAdmin", "RampAgent"}


@bp.route("/gse-allocations", methods=["POST"])
def create_allocation():
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    body = helpers.get_body()

    # existence (priority 3): flight_id then equipment_id (declaration order)
    flight = None
    if body.get("flight_id") is not None:
        flight = db.flights.get(body["flight_id"])
        if flight is None:
            raise errors.not_found("Flight not found.")
    equipment = None
    if body.get("equipment_id") is not None:
        equipment = db.ground_equipment.get(body["equipment_id"])
        if equipment is None:
            raise errors.not_found("GSE asset not found.")

    # well-formedness (priority 4)
    helpers.require_fields(body, ["flight_id", "equipment_id", "start_utc", "end_utc"])
    start_dt, start_raw = helpers.parse_dt(body["start_utc"], "start_utc")
    end_dt, end_raw = helpers.parse_dt(body["end_utc"], "end_utc")
    if end_dt <= start_dt:
        raise errors.invalid_request("end_utc must be strictly later than start_utc.")

    # GSE cooldown conflict (priority 10)
    if occupancy.gse_conflicts(equipment["id"], start_dt, end_dt,
                               equipment["turnaround_minutes"]):
        raise errors.equipment_busy()

    rec = {
        "id": db.new_id(),
        "flight_id": flight["id"],
        "equipment_id": equipment["id"],
        "start_utc": start_raw,
        "end_utc": end_raw,
        "status": "HELD",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_create(rec)
    db.gse_allocations[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/gse-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.gse_allocations.get(aid)
    if rec is None:
        raise errors.not_found("GSE allocation not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/gse-allocations", methods=["GET"])
def list_allocations():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    flight_id = request.args.get("flight_id")
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    recs = list(db.gse_allocations.values())
    if flight_id is not None:
        recs = [r for r in recs if r.get("flight_id") == flight_id]
    if equipment_id is not None:
        recs = [r for r in recs if r.get("equipment_id") == equipment_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


@bp.route("/gse-allocations/<aid>/release", methods=["POST"])
def release(aid):
    _, role = authenticate()
    require_roles(role, {"RampAgent"})
    rec = db.gse_allocations.get(aid)
    if rec is None:
        raise errors.not_found("GSE allocation not found.")
    if rec["status"] != "HELD":
        raise errors.invalid_state("Allocation is not HELD.")
    rec["status"] = "RELEASED"
    db.touch(rec)
    return success(helpers.serialize(rec), status=200)
