"""Section routes: list/read, PATCH (schedule assignment), cancel, roster."""

from flask import Blueprint, request

import db
import domain
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_request, invalid_posture, invalid_state,
                    ERR_SECTION_ASSIGNMENT_INVALID, ERR_GRID_CONFLICT)
from validate import (new_record, touch, req_field, as_int, occ_early,
                      occ_required, fk_or_404, get_or_404)

bp = Blueprint("sections", __name__)


@bp.get("/scheduling/sections")
def list_sections():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.sections.values())
    for param, field in (("term_id", "term_id"), ("course_id", "course_id"),
                         ("teacher_id", "teacher_id"), ("room_id", "room_id"),
                         ("state", "state")):
        v = request.args.get(param)
        if v is not None:
            rows = [s for s in rows if s.get(field) == v]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.section(s) for s in page], limit, offset, total)


@bp.get("/scheduling/sections/<sid>")
def get_section(sid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.section(get_or_404(db.sections, sid)))


@bp.patch("/scheduling/sections/<sid>")
def patch_section(sid):
    require_role("Administrator")
    s = get_or_404(db.sections, sid)
    data = body()
    teacher_id = data.get("teacher_id")
    room_id = data.get("room_id")
    teacher = fk_or_404(db.teachers, teacher_id, "teacher_id")
    room = fk_or_404(db.rooms, room_id, "room_id")
    term = get_or_404(db.terms, s["term_id"])
    occ_early(data, term)
    if term["posture"] != "BUILDING":
        raise invalid_posture("Section scheduling requires the term to be "
                              "BUILDING")
    if s["state"] != "DRAFT":
        raise invalid_state("Only DRAFT sections can be scheduled")
    # Shape + numeric bounds (400).
    for name in ("teacher_id", "room_id", "period", "capacity"):
        req_field(data, name)
    occ_required(data)
    period = as_int(data["period"], "period")
    if not 1 <= period <= term["periods_per_day"]:
        raise invalid_request("period must be between 1 and periods_per_day")
    capacity = as_int(data["capacity"], "capacity")
    if capacity < 1:
        raise invalid_request("capacity must be >= 1")
    if capacity > min(term["max_students_per_section"], room["capacity"]):
        raise invalid_request("capacity must not exceed the smaller of the "
                              "term ceiling and the room capacity")
    # Assignment validity (422): qualification, room type, teacher load.
    course = db.courses.get(s["course_id"])
    qualified = any(q["teacher_id"] == teacher["id"]
                    and q["course_id"] == s["course_id"]
                    for q in db.qualifications.values())
    if not qualified:
        raise ApiError(ERR_SECTION_ASSIGNMENT_INVALID, 422,
                       "Teacher is not qualified for this course")
    if course and room["room_type"] != course["required_room_type"]:
        raise ApiError(ERR_SECTION_ASSIGNMENT_INVALID, 422,
                       "Room type does not match the course requirement")
    if domain.teacher_assigned_section_count(teacher["id"]) >= teacher["max_sections"]:
        raise ApiError(ERR_SECTION_ASSIGNMENT_INVALID, 422,
                       "Teacher has reached max_sections")
    # Grid conflicts (409): same (teacher, period) or (room, period).
    for other in db.sections.values():
        if (other["id"] == s["id"] or other["term_id"] != term["id"]
                or other["state"] == "CANCELLED"):
            continue
        if other.get("period") is None:
            continue
        if other.get("teacher_id") == teacher["id"] and other["period"] == period:
            raise ApiError(ERR_GRID_CONFLICT, 409,
                           "Another section already occupies this "
                           "teacher/period slot")
        if other.get("room_id") == room["id"] and other["period"] == period:
            raise ApiError(ERR_GRID_CONFLICT, 409,
                           "Another section already occupies this "
                           "room/period slot")
    s["teacher_id"] = teacher["id"]
    s["room_id"] = room["id"]
    s["period"] = period
    s["capacity"] = capacity
    s["state"] = "SCHEDULED"
    s["version"] += 1
    touch(s)
    term["version"] += 1
    touch(term)
    return success_object(ser.section(s))


@bp.post("/scheduling/sections/<sid>/cancel")
def cancel_section(sid):
    require_role("Administrator")
    s = get_or_404(db.sections, sid)
    term = get_or_404(db.terms, s["term_id"])
    if term["posture"] != "BUILDING":
        raise invalid_posture("Section cancellation requires BUILDING")
    if s["state"] != "SCHEDULED":
        raise invalid_state("Only SCHEDULED sections can be cancelled")
    if domain.section_enrolled_count(s["id"]) != 0:
        raise invalid_state("Only empty sections can be cancelled")
    s["state"] = "CANCELLED"
    touch(s)
    return success_object(ser.section(s))


@bp.get("/scheduling/sections/<sid>/roster")
def section_roster(sid):
    require_role("Administrator", "Counselor")
    s = get_or_404(db.sections, sid)
    rows = [e for e in db.schedule_entries.values()
            if e["section_id"] == s["id"]]
    state = request.args.get("state")
    if state is not None:
        rows = [e for e in rows if e["state"] == state]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.schedule_entry(e) for e in page],
                        limit, offset, total)
