"""Flight schedule routes: create, lifecycle, IROPS, reverse-FK lists."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success
from services import flight_cascade

bp = Blueprint("flights", __name__)

ALL_ROLES = {"OpsAdmin", "GateController", "RampAgent", "SlotCoordinator"}


@bp.route("/flights", methods=["POST"])
def create_flight():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["flight_no", "aircraft_wingspan_m", "sched_departure_utc"])

    flight_no = body["flight_no"]
    if not isinstance(flight_no, str):
        raise errors.invalid_request("flight_no must be a string.")
    wingspan = helpers.parse_number(body["aircraft_wingspan_m"], "aircraft_wingspan_m", minimum=0)

    dep_dt, dep_raw = helpers.parse_dt(body["sched_departure_utc"], "sched_departure_utc")

    arr_raw = None
    arr_dt = None
    if body.get("sched_arrival_utc") is not None:
        arr_dt, arr_raw = helpers.parse_dt(body["sched_arrival_utc"], "sched_arrival_utc")

    min_turn = 45
    if body.get("min_turn_minutes") is not None:
        min_turn = helpers.parse_int(body["min_turn_minutes"], "min_turn_minutes", minimum=0)

    # scheduled_turn_minutes = (dep - arr) whole minutes, null if arrival null.
    if arr_dt is None:
        scheduled_turn = None
    else:
        scheduled_turn = helpers.whole_minutes(arr_dt, dep_dt)

    rec = {
        "id": db.new_id(),
        "flight_no": flight_no,
        "aircraft_wingspan_m": wingspan,
        "sched_arrival_utc": arr_raw,
        "sched_departure_utc": dep_raw,
        "min_turn_minutes": min_turn,
        "schedule_status": "SCHEDULED",
        "handling_status": "UNASSIGNED",
        "scheduled_turn_minutes": scheduled_turn,
    }
    db.stamp_create(rec)
    db.flights[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/flights/<fid>", methods=["GET"])
def get_flight(fid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = db.flights.get(fid)
    if rec is None:
        raise errors.not_found("Flight not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/flights", methods=["GET"])
def list_flights():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    schedule_status = request.args.get("schedule_status")
    handling_status = request.args.get("handling_status")
    recs = list(db.flights.values())
    if schedule_status is not None:
        recs = [r for r in recs if r["schedule_status"] == schedule_status]
    if handling_status is not None:
        recs = [r for r in recs if r["handling_status"] == handling_status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


def _get_flight_or_404(fid):
    rec = db.flights.get(fid)
    if rec is None:
        raise errors.not_found("Flight not found.")
    return rec


@bp.route("/flights/<fid>/activate", methods=["POST"])
def activate(fid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    flight = _get_flight_or_404(fid)
    if flight["schedule_status"] != "SCHEDULED":
        raise errors.invalid_state("Flight is not SCHEDULED.")
    flight["schedule_status"] = "ACTIVE"
    db.touch(flight)
    return success(helpers.serialize(flight), status=200)


@bp.route("/flights/<fid>/complete", methods=["POST"])
def complete(fid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    flight = _get_flight_or_404(fid)
    # state from-check first (priority 5)
    if flight["schedule_status"] != "ACTIVE":
        raise errors.invalid_state("Flight is not ACTIVE.")
    # cross-axis guard (priority 6)
    if flight["handling_status"] != "DEPARTED":
        raise errors.cross_state_blocked("Handling has not reached DEPARTED.")
    flight["schedule_status"] = "COMPLETED"
    db.touch(flight)
    return success(helpers.serialize(flight), status=200)


@bp.route("/flights/<fid>/irops-cancel", methods=["POST"])
def irops_cancel(fid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    flight = _get_flight_or_404(fid)
    if flight["schedule_status"] not in ("SCHEDULED", "ACTIVE"):
        raise errors.invalid_state("Flight cannot be cancelled from its current state.")
    flight_cascade.irops_cancel_cascade(flight)
    flight["schedule_status"] = "CANCELLED"
    flight["handling_status"] = "UNASSIGNED"
    db.touch(flight)
    return success(helpers.serialize(flight), status=200)


@bp.route("/flights/<fid>/irops-divert", methods=["POST"])
def irops_divert(fid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    flight = _get_flight_or_404(fid)
    if flight["schedule_status"] != "ACTIVE":
        raise errors.invalid_state("Flight can only be diverted from ACTIVE.")
    flight_cascade.irops_divert_cascade(flight)
    flight["schedule_status"] = "DIVERTED"
    flight["handling_status"] = "UNASSIGNED"
    db.touch(flight)
    return success(helpers.serialize(flight), status=200)


# ---- reverse-FK list endpoints --------------------------------------------


def _flight_child_list(fid, collection, fk="flight_id", allowed=None):
    _, role = authenticate()
    require_roles(role, allowed)
    if fid not in db.flights:
        raise errors.not_found("Flight not found.")
    status = request.args.get("status")
    recs = [r for r in collection.values() if r.get(fk) == fid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


@bp.route("/flights/<fid>/gate-assignments", methods=["GET"])
def flight_gate_assignments(fid):
    return _flight_child_list(fid, db.gate_assignments,
                              allowed={"OpsAdmin", "GateController", "RampAgent"})


@bp.route("/flights/<fid>/slot-permits", methods=["GET"])
def flight_slot_permits(fid):
    return _flight_child_list(fid, db.slot_permits,
                              allowed={"OpsAdmin", "SlotCoordinator"})


@bp.route("/flights/<fid>/cute-allocations", methods=["GET"])
def flight_cute_allocations(fid):
    return _flight_child_list(fid, db.cute_allocations,
                              allowed={"OpsAdmin", "RampAgent"})


@bp.route("/flights/<fid>/gse-allocations", methods=["GET"])
def flight_gse_allocations(fid):
    return _flight_child_list(fid, db.gse_allocations,
                              allowed={"OpsAdmin", "RampAgent"})
