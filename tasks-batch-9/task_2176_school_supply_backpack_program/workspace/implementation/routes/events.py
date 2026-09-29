"""Volunteer sessions and distribution events."""
from datetime import timedelta

from flask import Blueprint

import calc
import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import (ALL_ROLES, PROGRAM_DIRECTOR, SCHOOL_LIAISON,
                        SITE_COORDINATOR, auth, school_scope, site_scope)

bp = Blueprint("events", __name__)

BUFFER = timedelta(minutes=calc.SITE_TURNOVER_BUFFER_MINUTES)


# --------------------------------------------------------------------------
# VolunteerEvent
# --------------------------------------------------------------------------
@bp.post("/volunteer-events")
def create_volunteer_event():
    user_id, role = auth([SITE_COORDINATOR])
    data = v.body()
    site_id = v.req_id(data, "collection_site_id")
    event_type = v.req_enum(data, "event_type", v.VOLUNTEER_TYPES)
    window_start, window_end = v.req_window(data)
    volunteer_count = v.req_int(data, "volunteer_count", minimum=1)
    minor_count = v.opt_int(data, "minor_volunteer_count", 0, minimum=0,
                            maximum=volunteer_count)
    supervisor_count = v.opt_int(data, "adult_supervisor_count", 0, minimum=0)

    site = find.site(site_id)
    site_scope(role, user_id, site["id"])

    # 12 — child-safety supervision ratio.
    if supervisor_count < calc.required_supervisors(minor_count):
        raise ApiError("ERR_SUPERVISION_RATIO_UNMET")

    cycle = db.drive_cycles.get(site["drive_cycle_id"])
    # 18 — window containment inside the cycle window.
    if (cycle is None or window_start < cycle["window_start"]
            or window_end > cycle["window_end"]):
        raise ApiError("ERR_WINDOW_OUTSIDE_CYCLE")

    # 20 — buffered site occupation conflict.
    for other in db.volunteer_events.values():
        if other["collection_site_id"] != site["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if (window_start < other["window_end"] + BUFFER
                and other["window_start"] < window_end + BUFFER):
            raise ApiError("ERR_SITE_WINDOW_CONFLICT")

    open_kit_demand = sum(
        e["seat_capacity"] - e["served_student_count"]
        for e in derive.events_of_cycle(site["drive_cycle_id"])
        if e["status"] in ("DRAFT", "PUBLISHED"))

    planned = calc.volunteer_throughput(
        event_type, window_start, window_end, volunteer_count,
        site["bin_capacity"], open_kit_demand)

    rec = base_record()
    rec.update({
        "collection_site_id": site["id"],
        "event_type": event_type,
        "window_start": window_start,
        "window_end": window_end,
        "volunteer_count": volunteer_count,
        "minor_volunteer_count": minor_count,
        "adult_supervisor_count": supervisor_count,
        "status": "SCHEDULED",
        "planned_kit_capacity": planned,
        "assembled_kit_count": 0,
    })
    db.volunteer_events[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.post("/volunteer-events/<event_id>/transitions")
def move_volunteer_event(event_id):
    user_id, role = auth([SITE_COORDINATOR])
    data = v.body()
    target = v.target_status(data)
    assembled = v.opt_int(data, "assembled_kit_count", None, minimum=0)

    event = find.volunteer_event(event_id)
    site_scope(role, user_id, event["collection_site_id"])
    site = db.collection_sites.get(event["collection_site_id"])
    current = event["status"]

    if target not in v.VOLUNTEER_STATUSES:
        raise ApiError("ERR_INVALID_EVENT_STATE")

    if target == "IN_PROGRESS":
        if current != "SCHEDULED":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        if site is None or site["operational_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        event["status"] = "IN_PROGRESS"
    elif target == "COMPLETED":
        if current != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        if assembled is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Missing required field 'assembled_kit_count'.")
        if assembled > event["planned_kit_capacity"]:
            raise ApiError("ERR_ASSEMBLY_OVER_CAPACITY")
        event["status"] = "COMPLETED"
        event["assembled_kit_count"] = assembled
    elif target == "CANCELLED":
        if current not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_EVENT_STATE")
        event["status"] = "CANCELLED"
    else:
        raise ApiError("ERR_INVALID_EVENT_STATE")

    touch(event)
    return resp.ok(event)


# --------------------------------------------------------------------------
# DistributionEvent
# --------------------------------------------------------------------------
def _throughput_ok(school, window_start, window_end, seat_capacity, exclude_id=None):
    overlapping = []
    for other in derive.events_of_school(school["id"]):
        if other["id"] == exclude_id:
            continue
        if other["status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
            continue
        # Closed intervals: touching endpoints DO overlap.
        if window_start <= other["window_end"] and other["window_start"] <= window_end:
            overlapping.append(other)
    instants = [window_start]
    for other in overlapping:
        if window_start <= other["window_start"] <= window_end:
            instants.append(other["window_start"])
    for instant in instants:
        total = seat_capacity + sum(
            o["seat_capacity"] for o in overlapping
            if o["window_start"] <= instant <= o["window_end"])
        if total > school["max_concurrent_seats"]:
            return False
    return True


@bp.post("/distribution-events")
def create_distribution_event():
    user_id, role = auth([SCHOOL_LIAISON])
    data = v.body()
    school_id = v.req_id(data, "school_id")
    cycle_id = v.req_id(data, "drive_cycle_id")
    grade_band = v.req_enum(data, "grade_band", v.GRADE_BANDS)
    window_start, window_end = v.req_window(data)
    seat_capacity = v.req_int(data, "seat_capacity", minimum=1)

    school = find.school(school_id)
    cycle = find.cycle(cycle_id)
    school_scope(role, user_id, school["id"])

    if school["partnership_status"] != "ACTIVE":
        raise ApiError("ERR_SCHOOL_PARTNERSHIP_INACTIVE")
    if window_start < cycle["window_start"] or window_end > cycle["window_end"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_CYCLE")
    if not _throughput_ok(school, window_start, window_end, seat_capacity):
        raise ApiError("ERR_SCHOOL_THROUGHPUT_EXCEEDED")

    rec = base_record()
    rec.update({
        "school_id": school["id"],
        "drive_cycle_id": cycle["id"],
        "grade_band": grade_band,
        "window_start": window_start,
        "window_end": window_end,
        "seat_capacity": seat_capacity,
        "status": "DRAFT",
        "provisional_fill_pct": 0.00,
        "final_fill_pct": 0.00,
        "confirmed_count": 0,
        "waitlist_count": 0,
        "served_student_count": 0,
    })
    db.distribution_events[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/distribution-events/<event_id>")
def read_distribution_event(event_id):
    auth(ALL_ROLES)
    return resp.ok(find.distribution_event(event_id))


@bp.get("/distribution-events")
def list_distribution_events():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    school_id = v.query_id("school_id")
    cycle_id = v.query_id("drive_cycle_id")
    status = v.query_enum("status", v.EVENT_STATUSES)
    rows = list(db.distribution_events.values())
    if school_id:
        rows = [r for r in rows if r["school_id"] == school_id]
    if cycle_id:
        rows = [r for r in rows if r["drive_cycle_id"] == cycle_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


@bp.get("/distribution-events/<event_id>/student-registrations")
def list_event_registrations(event_id):
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.query_enum("eligibility_status", v.REGISTRATION_STATUSES)
    event = find.distribution_event(event_id)
    rows = [r for r in db.student_registrations.values()
            if r["distribution_event_id"] == event["id"]]
    if status:
        rows = [r for r in rows if r["eligibility_status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


def _withdraw_all(event):
    for reg in derive.registrations_of_event(event["id"]):
        if reg["eligibility_status"] not in (
                "PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED"):
            continue
        was_confirmed = reg["eligibility_status"] == "CONFIRMED"
        reg["eligibility_status"] = "WITHDRAWN"
        if was_confirmed:
            derive.release_units(reg, event)
        touch(reg)


def _close_cascade(event, cycle, school):
    # HOP 1 + HOP 2 — confirmed become no-shows and give back their units.
    confirmed = derive.waitlist_order(
        [r for r in derive.registrations_of_event(event["id"])
         if r["eligibility_status"] == "CONFIRMED"])
    for reg in confirmed:
        reg["eligibility_status"] = "NO_SHOW"
        derive.release_units(reg, event)
        touch(reg)
    # Everything still open is withdrawn; none of those hold a reservation.
    for reg in derive.registrations_of_event(event["id"]):
        if reg["eligibility_status"] in ("PENDING", "VERIFIED", "WAITLISTED"):
            reg["eligibility_status"] = "WITHDRAWN"
            touch(reg)
    derive.recompute_event_counters(event)
    # HOP 3
    if cycle is not None:
        derive.recompute_cycle_inventory(cycle)
        touch(cycle)
    if school is not None:
        derive.recompute_school(school)


@bp.post("/distribution-events/<event_id>/transitions")
def move_distribution_event(event_id):
    user_id, role = auth([SCHOOL_LIAISON, PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)

    event = find.distribution_event(event_id)
    school_scope(role, user_id, event["school_id"])
    school = db.schools.get(event["school_id"])
    cycle = db.drive_cycles.get(event["drive_cycle_id"])
    current = event["status"]

    if target not in v.EVENT_STATUSES:
        raise ApiError("ERR_INVALID_EVENT_STATE")

    if target == "PUBLISHED":
        if current != "DRAFT":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        if school is None or school["partnership_status"] != "ACTIVE":
            raise ApiError("ERR_SCHOOL_PARTNERSHIP_INACTIVE")
        spec, lines = derive.spec_lines_for_event(event)
        if spec is None or len(lines) < 1:
            raise ApiError("ERR_KIT_SPEC_NOT_PUBLISHED")
        if cycle is None or cycle["status"] not in (
                "COLLECTING", "SORTING", "DISTRIBUTION"):
            raise ApiError("ERR_CYCLE_PHASE_INVALID")
        if not _throughput_ok(school, event["window_start"], event["window_end"],
                              event["seat_capacity"], exclude_id=event["id"]):
            raise ApiError("ERR_SCHOOL_THROUGHPUT_EXCEEDED")
        event["status"] = "PUBLISHED"
        event["provisional_fill_pct"] = derive.provisional_fill(event)
        touch(event)
    elif target == "LOCKED":
        if current != "PUBLISHED":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        if cycle is None or cycle["status"] != "DISTRIBUTION":
            raise ApiError("ERR_CYCLE_PHASE_INVALID")
        event["status"] = "LOCKED"
        event["final_fill_pct"] = derive.final_fill(event)
        touch(event)
        if school is not None:
            derive.recompute_school(school)
    elif target == "CLOSED":
        if current != "LOCKED":
            raise ApiError("ERR_INVALID_EVENT_STATE")
        event["status"] = "CLOSED"
        touch(event)
        _close_cascade(event, cycle, school)
    elif target == "CANCELLED":
        if current not in ("DRAFT", "PUBLISHED"):
            raise ApiError("ERR_INVALID_EVENT_STATE")
        event["status"] = "CANCELLED"
        _withdraw_all(event)
        derive.recompute_event_counters(event)
        touch(event)
        if cycle is not None:
            derive.recompute_cycle_inventory(cycle)
        if school is not None:
            derive.recompute_school(school, bump=False)
    else:
        raise ApiError("ERR_INVALID_EVENT_STATE")

    return resp.ok(event)
