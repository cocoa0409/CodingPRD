"""Crew and crew-assignment endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("crews", __name__)

BUFFER = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)


@bp.post("/vm/crews")
@endpoint(["ContractorPlanner"])
def create_crew():
    data = V.body()
    crew_code = V.as_string(data, "crew_code")
    crew_type = V.as_enum(data, "crew_type", C.CREW_TYPES)
    headcount = V.as_integer(data, "headcount", minimum=1, maximum=12)
    rate = V.as_integer(data, "hourly_rate_cents", minimum=0)
    district = V.as_string(data, "home_district")
    V.unique(store.crews, "crew_code", crew_code)

    rec = store.new_record()
    rec.update({
        "crew_code": crew_code,
        "crew_type": crew_type,
        "headcount": headcount,
        "hourly_rate_cents": rate,
        "home_district": district,
        "status": "AVAILABLE",
        "_storm_event_id": None,
    })
    store.crews[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.get("/vm/crews/<cid>")
@endpoint(ALL_ROLES)
def get_crew(cid):
    return envelope.ok(store.public(V.find(store.crews, cid, "ERR_CREW_NOT_FOUND")))


@bp.get("/vm/crews")
@endpoint(ALL_ROLES)
def list_crews():
    return envelope.list_response(list(store.crews.values()), {
        "status": request.args.get("status"),
        "crew_type": request.args.get("crew_type"),
        "home_district": request.args.get("home_district"),
    })


@bp.post("/vm/crew-assignments")
@endpoint(["ContractorPlanner"])
def create_assignment():
    data = V.body()
    work_order = V.body_fk(data, "work_order_id", store.work_orders,
                           "ERR_WORK_ORDER_NOT_FOUND")
    crew = V.body_fk(data, "crew_id", store.crews, "ERR_CREW_NOT_FOUND")
    if work_order is None:
        V.require(data, "work_order_id")
    if crew is None:
        V.require(data, "crew_id")
    start_at = V.as_datetime(data, "start_at")
    end_at = V.as_datetime(data, "end_at")

    if crew.get("status") == "STORM_DEPLOYED":
        raise ApiError("ERR_CREW_UNAVAILABLE", "a STORM_DEPLOYED crew cannot be booked")

    for other in services.crew_assignments_of(crew["id"]):
        if other.get("status") not in ("SCHEDULED", "ACTIVE"):
            continue
        other_start = store.parse_datetime(other.get("start_at"))
        other_end = store.parse_datetime(other.get("end_at"))
        if other_start is None or other_end is None:
            continue
        if start_at < other_end + BUFFER and end_at + BUFFER > other_start:
            raise ApiError("ERR_CREW_SCHEDULE_CONFLICT",
                           "the booking collides with another live booking of this crew")

    rec = store.new_record()
    rec.update({
        "work_order_id": work_order["id"],
        "crew_id": crew["id"],
        "preempted_by_storm_event_id": None,
        "start_at": store.iso(start_at),
        "end_at": store.iso(end_at),
        "status": "SCHEDULED",
    })
    store.crew_assignments[rec["id"]] = rec
    if crew.get("status") == "AVAILABLE":
        crew["status"] = "ASSIGNED"
    store.touch(crew)
    return envelope.created(store.public(rec))


@bp.post("/vm/crew-assignments/<aid>/release")
@endpoint(["ContractorPlanner"])
def release_assignment(aid):
    assignment = V.find(store.crew_assignments, aid, "ERR_CREW_ASSIGNMENT_NOT_FOUND")
    services.require_state(assignment, "crew_assignment", ["SCHEDULED", "ACTIVE"])
    assignment["status"] = "RELEASED"
    store.touch(assignment)
    crew = services.crew_of_assignment(assignment)
    services.free_crew_if_idle(crew, bump=False)
    store.touch(crew)
    return envelope.ok(store.public(assignment))


@bp.get("/vm/crew-assignments/<aid>")
@endpoint(ALL_ROLES)
def get_assignment(aid):
    rec = V.find(store.crew_assignments, aid, "ERR_CREW_ASSIGNMENT_NOT_FOUND")
    return envelope.ok(store.public(rec))


@bp.get("/vm/crew-assignments")
@endpoint(ALL_ROLES)
def list_assignments():
    return envelope.list_response(list(store.crew_assignments.values()), {
        "work_order_id": request.args.get("work_order_id"),
        "crew_id": request.args.get("crew_id"),
        "preempted_by_storm_event_id": request.args.get("preempted_by_storm_event_id"),
        "status": request.args.get("status"),
    })
