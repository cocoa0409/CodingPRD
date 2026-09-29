"""Installation schedules: booking, execution and cancellation (PRD 3.8)."""

from flask import Blueprint

import constants as C
from clock import parse_instant
from db import db, new_record, public, touch
from errors import fail
from middleware import require, require_crew_ownership
from response import created, ok
from routes.common import list_response
from services import cascade
from services.cost import inside_summer_window
from validation import (
    add_days, as_date, get_body, lookup, need_date, need_enum, need_string,
    opt_bool, resolve_body_fk,
)

bp = Blueprint("schedules", __name__)


def _live_schedules():
    return [s for s in db.schedules.values() if s["status"] in ("PLANNED", "IN_PROGRESS")]


@bp.post("/installation-schedules")
def book_schedule():
    actor = require(["OperationsScheduler", "DistrictAdmin"])
    body = get_body()
    # rule 5
    req = resolve_body_fk("request", body, "placement_request_id")
    crew = resolve_body_fk("crew", body, "installation_crew_id")
    # rule 6
    if req is None:
        need_string(body, "placement_request_id")
    if crew is None:
        need_string(body, "installation_crew_id")
    work_type = need_enum(body, "work_type", C.WORK_TYPES)
    window_start, start_date = need_date(body, "window_start")
    window_end, end_date = need_date(body, "window_end")
    waiver = opt_bool(body, "off_summer_waiver", False)

    # rule 12
    if req["status"] != "PERMITTED":
        fail("ERR_REQUEST_NOT_PERMITTED",
             "The placement request is %s, not PERMITTED." % req["status"])
    for sibling in db.schedules.values():
        if (sibling["placement_request_id"] == req["id"]
                and sibling["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED")):
            fail("ERR_REQUEST_NOT_PERMITTED",
                 "That placement request already holds a live installation window.")
    # rule 33
    if work_type not in crew["certified_work_types"]:
        fail("ERR_CREW_NOT_CERTIFIED",
             "The crew is not certified for %s work." % work_type)
    # rule 34
    if end_date < start_date:
        fail("ERR_INVALID_WINDOW",
             "window_end must not be earlier than window_start.")
    # rule 35
    if not waiver and not inside_summer_window(window_start, window_end):
        fail("ERR_OUTSIDE_SUMMER_WINDOW",
             "The window must lie inside June 15 through August 15 of one year.")
    # rule 36
    if waiver and actor.role != "DistrictAdmin":
        fail("ERR_WAIVER_ROLE_REQUIRED",
             "Only a DistrictAdmin may sign an off-summer work waiver.")
    # rule 37
    for permit in db.permits.values():
        if (permit["placement_request_id"] == req["id"]
                and permit["status"] == "APPROVED"):
            approved = parse_instant(permit["approved_on"])
            if approved is None:
                continue
            expiry = add_days(approved.date(), C.PERMIT_VALIDITY_DAYS)
            if start_date > expiry:
                fail("ERR_PERMIT_EXPIRED",
                     "Permit %s expired on %s." % (permit["permit_type"], expiry))
    # rule 38: pad occupation, closed intervals with a 7 day turnaround buffer
    for other in _live_schedules():
        other_req = db.requests.get(other["placement_request_id"])
        if other_req is None or other_req["id"] == req["id"]:
            continue
        if other_req["placement_site_id"] != req["placement_site_id"]:
            continue
        other_start = as_date(other["window_start"])
        other_end = as_date(other["window_end"])
        clear_after = (start_date - other_end).days > C.PAD_TURNAROUND_BUFFER_DAYS
        clear_before = (other_start - end_date).days > C.PAD_TURNAROUND_BUFFER_DAYS
        if not (clear_after or clear_before):
            fail("ERR_PAD_WINDOW_CONFLICT",
                 "The pad turnaround buffer conflicts with another booked window.")
    # rule 39: crew capacity, half-open intervals
    overlapping = 0
    for other in _live_schedules():
        if other["installation_crew_id"] != crew["id"]:
            continue
        other_start = as_date(other["window_start"])
        other_end = as_date(other["window_end"])
        if start_date < other_end and other_start < end_date:
            overlapping += 1
    if overlapping >= crew["max_concurrent_jobs"]:
        fail("ERR_CREW_CAPACITY_EXCEEDED",
             "The crew already holds %d overlapping windows." % overlapping)

    rec = new_record({
        "placement_request_id": req["id"],
        "installation_crew_id": crew["id"],
        "work_type": work_type,
        "window_start": window_start,
        "window_end": window_end,
        "off_summer_waiver": waiver,
        "status": "PLANNED",
        "cancellation_reason": None,
    })
    db.schedules[rec["id"]] = rec

    req["status"] = "SCHEDULED"
    touch(req)
    return created(public(rec))


@bp.get("/installation-schedules/<schedule_id>")
def read_schedule(schedule_id):
    require(C.ANY_ROLE)
    return ok(public(lookup("schedule", schedule_id)))


@bp.get("/installation-schedules")
def list_schedules():
    require(C.ANY_ROLE)
    return list_response(
        db.schedules, ["placement_request_id", "installation_crew_id", "status"])


@bp.post("/installation-schedules/<schedule_id>/start")
def start_schedule(schedule_id):
    actor = require(["OperationsScheduler", "CrewLead"])
    sched = lookup("schedule", schedule_id)
    # rule 3
    require_crew_ownership(actor, sched)
    # rule 10
    if sched["status"] != "PLANNED":
        fail("ERR_SCHEDULE_STATE_INVALID",
             "A schedule in %s cannot be started." % sched["status"])
    req = db.requests[sched["placement_request_id"]]
    if req["status"] != "SCHEDULED":
        fail("ERR_REQUEST_STATE_INVALID",
             "The owning placement request is %s, not SCHEDULED." % req["status"])

    sched["status"] = "IN_PROGRESS"
    touch(sched)
    return ok(public(sched))


@bp.post("/installation-schedules/<schedule_id>/complete")
def complete_schedule(schedule_id):
    actor = require(["OperationsScheduler", "CrewLead"])
    sched = lookup("schedule", schedule_id)
    # rule 3
    require_crew_ownership(actor, sched)
    # rule 10
    if sched["status"] != "IN_PROGRESS":
        fail("ERR_SCHEDULE_STATE_INVALID",
             "A schedule in %s cannot be completed." % sched["status"])
    req = db.requests[sched["placement_request_id"]]
    if req["status"] != "SCHEDULED":
        fail("ERR_REQUEST_STATE_INVALID",
             "The owning placement request is %s, not SCHEDULED." % req["status"])
    unit = db.units.get(req.get("portable_unit_id"))
    site = db.sites.get(req.get("placement_site_id"))
    # rule 19
    if unit is None or not unit["ada_ramp_installed"] or site is None \
            or not site["ada_path_of_travel_compliant"]:
        fail("ERR_ADA_NONCOMPLIANT",
             "The unit ramp and the pad accessible path of travel must both comply.")

    sched["status"] = "COMPLETED"
    touch(sched)
    cascade.install_complete(sched, req)
    return ok(public(sched))


@bp.post("/installation-schedules/<schedule_id>/cancel")
def cancel_schedule(schedule_id):
    require(["OperationsScheduler"])
    sched = lookup("schedule", schedule_id)
    body = get_body()
    reason = need_string(body, "reason", 1, 2000)
    # rule 10
    if sched["status"] not in ("PLANNED", "IN_PROGRESS"):
        fail("ERR_SCHEDULE_STATE_INVALID",
             "A schedule in %s cannot be cancelled." % sched["status"])

    sched["status"] = "CANCELLED"
    sched["cancellation_reason"] = reason
    touch(sched)

    req = db.requests.get(sched["placement_request_id"])
    if req is not None and req["status"] == "SCHEDULED":
        req["status"] = "PERMITTED"
        touch(req)
    return ok(public(sched))
