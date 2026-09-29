"""Crew assignments: certification, visa, duty exposure, windows and pads."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import validators as v
from errors import fail, invalid
from middleware import (ROLE_CREW_CHIEF, ROLE_GENERAL_MANAGER, ROLE_LOT_BOSS,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("crew", __name__)

CREW_ROLES = ("SETUP", "RIDE_OPERATOR", "TEARDOWN", "TICKETING")
STOP_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                   ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS)
WORKER_READ_ROLES = STOP_READ_ROLES + (ROLE_CREW_CHIEF,)


@bp.post("/crew-assignments")
def create_assignment():
    require_role(ROLE_LOT_BOSS)
    body = v.get_body()
    stop = v.body_ref(body, "route_stop_id", "route_stops")
    worker = v.body_ref(body, "worker_id", "workers")
    if stop is None:
        v.req_str(body, "route_stop_id")
    if worker is None:
        v.req_str(body, "worker_id")
    crew_role = v.req_enum(body, "crew_role", CREW_ROLES)
    start_raw, shift_start = v.req_dt(body, "shift_start")
    end_raw, shift_end = v.req_dt(body, "shift_end")
    if shift_end <= shift_start:
        invalid("shift_end must be after shift_start.")

    # 1. certification
    if crew_role == "RIDE_OPERATOR":
        certified = worker.get("certified_ride_classes") or []
        classes = set()
        for alloc in calc.allocations_of_stop(stop["id"], calc.ALLOC_ACTIVE):
            ride = db.store.rides.get(alloc["ride_id"])
            if ride is not None:
                classes.add(ride["ride_class"])
        if not classes & set(certified):
            fail(errors.ERR_WORKER_NOT_CERTIFIED,
                 "The worker is certified for none of the lot's rides.")

    # 2. visa
    if worker["employment_type"] == "H2B_VISA":
        expires = calc.dt(worker, "visa_expires_on")
        if expires is not None and shift_end > expires:
            fail(errors.ERR_WORKER_VISA_LAPSED,
                 "The shift runs past the worker's H-2B authorization.")

    # 3. consecutive days inside the jurisdiction
    jurisdiction = calc.jurisdiction_of(stop)
    if jurisdiction is not None:
        run = calc.worker_consecutive_days(
            worker["id"], jurisdiction["id"],
            extra=calc.covered_dates(shift_start, shift_end))
        if run > int(jurisdiction["max_consecutive_work_days"]):
            fail(errors.ERR_CONSECUTIVE_DAYS_EXCEEDED,
                 "The worker would exceed the jurisdiction's consecutive-day "
                 "ceiling.")

    # 4. overlap against the worker's other SCHEDULED shifts
    for other in calc.assignments_of_worker(worker["id"], ("SCHEDULED",)):
        other_start = calc.dt(other, "shift_start")
        other_end = calc.dt(other, "shift_end")
        if shift_start < other_end and other_start < shift_end:
            fail(errors.ERR_CREW_SHIFT_OVERLAP,
                 "The worker already holds a shift over this interval.")

    # 5. role window
    if crew_role in ("SETUP", "TEARDOWN"):
        lo = calc.dt(stop, "load_in_start")
        hi = calc.dt(stop, "teardown_deadline")
    else:
        lo = calc.dt(stop, "open_date")
        hi = calc.dt(stop, "close_date")
    if shift_start < lo or shift_end > hi:
        fail(errors.ERR_SHIFT_OUTSIDE_STOP_WINDOW,
             "The shift lies outside the window its role permits.")

    # 6. housing pads
    housing_pad_assigned = bool(worker["housing_required"])
    if housing_pad_assigned:
        venue = calc.venue_of(stop)
        used = len([a for a in calc.assignments_of_stop(stop["id"], ("SCHEDULED",))
                    if a.get("housing_pad_assigned")])
        available = int(venue["housing_pads_available"]) if venue else 0
        if used + 1 > available:
            fail(errors.ERR_HOUSING_PADS_EXHAUSTED,
                 "The lot has no bunkhouse pad left.")

    shift_hours, cost_cents = calc.assignment_cost(worker, crew_role, shift_start,
                                                   shift_end)
    row = db.create(db.store.crew_assignments, {
        "route_stop_id": stop["id"],
        "worker_id": worker["id"],
        "crew_role": crew_role,
        "shift_start": start_raw,
        "shift_end": end_raw,
        "shift_hours": shift_hours,
        "cost_cents": cost_cents,
        "housing_pad_assigned": housing_pad_assigned,
        "status": "SCHEDULED",
    })
    db.touch(stop)
    db.touch(worker)
    return created(ser.crew_assignment(row))


@bp.get("/route-stops/<stop_id>/crew-assignments")
def list_stop_assignments(stop_id):
    require_role(*STOP_READ_ROLES)
    stop = v.path_row("route_stops", stop_id)
    rows = calc.assignments_of_stop(stop["id"])
    crew_role = request.args.get("crew_role")
    status = request.args.get("status")
    if crew_role:
        rows = [r for r in rows if r["crew_role"] == crew_role]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.crew_assignment)


@bp.get("/workers/<worker_id>/crew-assignments")
def list_worker_assignments(worker_id):
    caller = require_role(*WORKER_READ_ROLES)
    if caller.role == ROLE_CREW_CHIEF and caller.user_id != worker_id:
        fail(errors.ERR_ROLE_NOT_PERMITTED,
             "A crew chief may read only their own roster.")
    worker = v.path_row("workers", worker_id)
    rows = calc.assignments_of_worker(worker["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.crew_assignment)


@bp.post("/crew-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    require_role(ROLE_LOT_BOSS)
    assignment = v.path_row("crew_assignments", assignment_id)
    stop = db.store.route_stops.get(assignment["route_stop_id"])
    if stop is None or stop["status"] == "CLOSED":
        fail(errors.ERR_STOP_STATE_INVALID,
             "A shift on a CLOSED lot may not be cancelled.")
    if assignment["status"] != "SCHEDULED":
        fail(errors.ERR_ASSIGNMENT_STATE_INVALID,
             "Only a SCHEDULED shift may be cancelled.")
    assignment["status"] = "RELEASED"
    db.touch(assignment)
    db.touch(stop)
    worker = db.store.workers.get(assignment["worker_id"])
    if worker is not None:
        db.touch(worker)
    return ok(ser.crew_assignment(assignment))
