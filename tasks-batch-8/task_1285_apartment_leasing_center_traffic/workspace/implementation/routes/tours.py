"""Tour endpoints (guided/self-guided scheduling with availability sync)."""
from datetime import timedelta

from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import AGENT, PM, auth
from response import ok, ok_list
from services import (
    available_units,
    get_inquiry,
    get_tour,
    maybe_revert_inquiry,
    ser_tour,
    sorted_created,
    stamp,
    touch,
)
from util import (
    apply_filters,
    as_dt,
    as_enum,
    as_str,
    body,
    pagination,
    required,
)

bp = Blueprint("tours", __name__)

STAFF = [PM, AGENT]
TOUR_TYPES = ("GUIDED", "SELF_GUIDED")
OUTCOMES = ("COMPLETED", "NO_SHOW")


def _count_conflicts(agent_id, start, end, buffer, exclude_id=None):
    """Count the agent's SCHEDULED guided tours whose buffered interval
    [tour.start, tour.end + buffer) overlaps the new [start, end + buffer).

    Half-open boundary: a gap of exactly buffer minutes is allowed
    (existing.end + buffer <= new.start, or symmetrically for the reverse).
    """
    conflicts = 0
    for t in DB["tours"].values():
        if t["id"] == exclude_id:
            continue
        if t["agent_id"] != agent_id or t["status"] != "SCHEDULED":
            continue
        if start < t["scheduled_end"] + buffer and t["scheduled_start"] < end + buffer:
            conflicts += 1
    return conflicts


def _self_guided_unit_check(inq):
    """SELF_GUIDED requires the floorplan of interest to have a unit available."""
    if inq["floorplan_id"]:
        fp = DB["floorplans"].get(inq["floorplan_id"])
        if fp is not None and available_units(fp) < 1:
            raise ApiError(
                "ERR_SELF_GUIDED_NO_UNIT",
                409,
                "SELF_GUIDED tour requires at least one available unit",
            )


@bp.post("/leasing/tours")
def create_tour():
    auth(STAFF)
    data = body()
    inquiry_id = as_str(required(data, "inquiry_id"), "inquiry_id")
    tour_type = as_enum(required(data, "tour_type"), "tour_type", TOUR_TYPES)
    scheduled_start = as_dt(required(data, "scheduled_start"), "scheduled_start")
    agent_id = data.get("agent_id")
    scheduled_end = None
    if tour_type == "GUIDED":
        if agent_id is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "agent_id is required for GUIDED tours"
            )
        as_str(agent_id, "agent_id")
        scheduled_end = as_dt(
            required(data, "scheduled_end"), "scheduled_end"
        )
    else:
        if agent_id is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "agent_id must be omitted for SELF_GUIDED tours",
            )
        # Any client-supplied scheduled_end is ignored for SELF_GUIDED tours.

    inq = get_inquiry(inquiry_id)
    agent = None
    if tour_type == "GUIDED":
        agent = DB["agents"].get(agent_id)
        if agent is None:
            raise ApiError("ERR_AGENT_NOT_FOUND", 404, "Agent does not exist")
        if not agent["active"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "An inactive agent cannot be assigned tours",
            )

    # State: no booking against a LOST or CONVERTED inquiry.
    if inq["status"] in ("LOST", "CONVERTED"):
        raise ApiError(
            "ERR_INQUIRY_NOT_ACTIVE",
            409,
            "Cannot schedule a tour for a LOST or CONVERTED inquiry",
        )

    prop = DB["properties"][inq["property_id"]]
    if tour_type == "SELF_GUIDED":
        # Availability sync (priority 6), then the server fixes the window.
        _self_guided_unit_check(inq)
        scheduled_end = scheduled_start + timedelta(
            minutes=prop["self_guided_window_minutes"]
        )
    else:
        # Interval rule, then the agent-calendar capacity rule (priority 7).
        if not scheduled_end > scheduled_start:
            raise ApiError(
                "ERR_INVALID_TIME_RANGE",
                400,
                "scheduled_end must be strictly after scheduled_start",
            )
        buffer = timedelta(minutes=prop["tour_buffer_minutes"])
        conflicts = _count_conflicts(agent_id, scheduled_start, scheduled_end, buffer)
        if conflicts >= agent["max_concurrent_tours"]:
            raise ApiError(
                "ERR_TOUR_TIME_CONFLICT",
                409,
                "Tour overlaps the agent's buffered intervals at capacity",
            )

    rec = {
        "id": new_id(),
        "inquiry_id": inquiry_id,
        "agent_id": agent_id if tour_type == "GUIDED" else None,
        "tour_type": tour_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
    }
    stamp(rec)
    DB["tours"][rec["id"]] = rec
    if inq["status"] == "CONTACTED":
        inq["status"] = "TOUR_SCHEDULED"
        touch(inq)
    return ok(ser_tour(rec), status=201)


@bp.get("/leasing/tours")
def list_tours():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["tours"].values(),
        [
            ("inquiry_id", "inquiry_id"),
            ("agent_id", "agent_id"),
            ("status", "status"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_tour(t) for t in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/tours/<tid>")
def get_one_tour(tid):
    auth(STAFF)
    return ok(ser_tour(get_tour(tid)))


@bp.post("/leasing/tours/<tid>/reschedule")
def reschedule_tour(tid):
    auth(STAFF)
    tour = get_tour(tid)
    data = body()
    scheduled_start = as_dt(required(data, "scheduled_start"), "scheduled_start")
    if tour["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_TOUR_INVALID_STATE", 409, "Only a SCHEDULED tour can be rescheduled"
        )
    inq = DB["inquiries"][tour["inquiry_id"]]
    prop = DB["properties"][inq["property_id"]]
    if tour["tour_type"] == "SELF_GUIDED":
        _self_guided_unit_check(inq)
        scheduled_end = scheduled_start + timedelta(
            minutes=prop["self_guided_window_minutes"]
        )
    else:
        scheduled_end = as_dt(required(data, "scheduled_end"), "scheduled_end")
        if not scheduled_end > scheduled_start:
            raise ApiError(
                "ERR_INVALID_TIME_RANGE",
                400,
                "scheduled_end must be strictly after scheduled_start",
            )
        buffer = timedelta(minutes=prop["tour_buffer_minutes"])
        agent = DB["agents"].get(tour["agent_id"])
        max_concurrent = agent["max_concurrent_tours"] if agent is not None else 1
        conflicts = _count_conflicts(
            tour["agent_id"],
            scheduled_start,
            scheduled_end,
            buffer,
            exclude_id=tour["id"],
        )
        if conflicts >= max_concurrent:
            raise ApiError(
                "ERR_TOUR_TIME_CONFLICT",
                409,
                "Tour overlaps the agent's buffered intervals at capacity",
            )
    tour["scheduled_start"] = scheduled_start
    tour["scheduled_end"] = scheduled_end
    touch(tour)
    return ok(ser_tour(tour))


@bp.post("/leasing/tours/<tid>/complete")
def complete_tour(tid):
    auth(STAFF)
    tour = get_tour(tid)
    data = body()
    outcome = as_enum(required(data, "outcome"), "outcome", OUTCOMES)
    if tour["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_TOUR_INVALID_STATE", 409, "Only a SCHEDULED tour can be completed"
        )
    tour["status"] = outcome
    touch(tour)
    if outcome == "NO_SHOW":
        inq = DB["inquiries"].get(tour["inquiry_id"])
        if inq is not None:
            maybe_revert_inquiry(inq)
    return ok(ser_tour(tour))


@bp.post("/leasing/tours/<tid>/cancel")
def cancel_tour(tid):
    auth(STAFF)
    tour = get_tour(tid)
    if tour["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_TOUR_INVALID_STATE", 409, "Only a SCHEDULED tour can be cancelled"
        )
    tour["status"] = "CANCELLED"
    touch(tour)
    inq = DB["inquiries"].get(tour["inquiry_id"])
    if inq is not None:
        maybe_revert_inquiry(inq)
    return ok(ser_tour(tour))
