"""Section routes: create (with instructor double-booking buffer), get,
status transition (with cancellation cascade), and reverse-reachability lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import enroll, helpers as h
from services import serialize
from services.core import share_day
from services.entities import new_common, touch

bp = Blueprint("sections", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")
SECTION_STATUSES = {"OPEN", "CLOSED", "CANCELLED"}

# Section lifecycle transitions (PRD §3.2).
SECTION_TRANSITIONS = {
    "OPEN": {"CLOSED", "CANCELLED"},
    "CLOSED": {"OPEN", "CANCELLED"},
    "CANCELLED": set(),
}


@bp.post("/sections")
def create_section():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    term_id = h.require_string(body, "term_id")
    course_id = h.require_string(body, "course_id")
    instructor_id = h.require_string(body, "instructor_id")
    section_code = h.require_string(body, "section_code")
    seat_capacity = h.require_int(body, "seat_capacity")
    waitlist_capacity = h.optional_int(body, "waitlist_capacity", 0)
    meeting_days = h.require_string(body, "meeting_days")
    meeting_start_min = h.require_int(body, "meeting_start_min")
    meeting_end_min = h.require_int(body, "meeting_end_min")

    if seat_capacity < 1:
        raise err("ERR_VALIDATION", "seat_capacity must be >= 1")
    if waitlist_capacity < 0:
        raise err("ERR_VALIDATION", "waitlist_capacity must be >= 0")
    if not (0 <= meeting_start_min <= 1439):
        raise err("ERR_VALIDATION", "meeting_start_min must be in 0..1439")
    if not (1 <= meeting_end_min <= 1440):
        raise err("ERR_VALIDATION", "meeting_end_min must be in 1..1440")
    if meeting_end_min <= meeting_start_min:
        raise err("ERR_VALIDATION", "meeting_end_min must exceed meeting_start_min")

    # existence checks (left-to-right: Term, then Course)
    h.get_term(term_id)
    h.get_course(course_id)
    instructor = h.get_instructor(instructor_id)

    # Instructor double-booking buffer check against the instructor's other
    # non-CANCELLED sections in the same term (PRD §3.2, buffered geometry).
    gap = instructor["gap_minutes"]
    for other in db.sections.values():
        if other["instructor_id"] != instructor_id:
            continue
        if other["term_id"] != term_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if not share_day(meeting_days, other["meeting_days"]):
            continue
        if (
            meeting_start_min < other["meeting_end_min"] + gap
            and other["meeting_start_min"] < meeting_end_min + gap
        ):
            raise err("ERR_INSTRUCTOR_DOUBLE_BOOKED", "Section violates the instructor's gap_minutes buffer")

    rec = new_common("Section")
    rec.update({
        "term_id": term_id,
        "course_id": course_id,
        "instructor_id": instructor_id,
        "section_code": section_code,
        "seat_capacity": seat_capacity,
        "seats_taken": 0,
        "waitlist_capacity": waitlist_capacity,
        "waitlist_count": 0,
        "meeting_days": meeting_days,
        "meeting_start_min": meeting_start_min,
        "meeting_end_min": meeting_end_min,
        "status": "OPEN",
    })
    db.sections[rec["id"]] = rec
    return ok_object(serialize.section(rec), 201)


@bp.get("/sections/<section_id>")
def get_section(section_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_section(section_id)
    return ok_object(serialize.section(rec), 200)


@bp.post("/sections/<section_id>/status")
def transition_section(section_id):
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()
    to_status = h.require_enum(body, "to_status", SECTION_STATUSES)

    section = h.get_section(section_id)
    cur = section["status"]
    if to_status not in SECTION_TRANSITIONS.get(cur, set()):
        raise err("ERR_INVALID_STATE", f"Transition {cur} -> {to_status} is not defined")

    section["status"] = to_status
    touch(section)

    if to_status == "CANCELLED":
        enroll.cancel_section_cascade(section)

    return ok_object(serialize.section(section), 200)


@bp.get("/sections/<section_id>/enrollments")
def list_section_enrollments(section_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_section(section_id)

    registration_status = request.args.get("registration_status")
    recs = [
        e for e in db.enrollments.values()
        if e["section_id"] == section_id
        and (registration_status is None or e["registration_status"] == registration_status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.enrollment(e) for e in page], limit, offset, total, 200)
