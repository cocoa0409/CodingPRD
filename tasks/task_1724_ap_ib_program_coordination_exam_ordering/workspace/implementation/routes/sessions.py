"""ExamSession endpoints (PRD 3.5, 3.6): scheduling gates, attendance, cancellation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_SESSION,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OUTSIDE_EXAM_WINDOW,
    ERR_REFERENCE_NOT_FOUND,
    ERR_ROOM_CAPACITY_INSUFFICIENT,
    ERR_ROOM_CONFLICT,
    ERR_ROOM_NOT_ACCOMMODATION_CAPABLE,
    ERR_SESSION_NOT_ENDED,
    ERR_TEACHER_NOT_AUTHORIZED,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.derived import authorized_teacher_count, course_seated_count
from services.serialize import serialize_session
from util import CLOCK
from validate import (
    get_body, opt_bool, reject_unknown_fields, req_datetime, req_int, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("exam_sessions", __name__)

ALL_READ = ["ApCoordinator", "Registrar", "Teacher", "Student"]
SESSION_FIELDS = {"course_id", "room_name", "room_capacity",
                  "room_supports_accommodations", "start_at", "end_at"}


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """[start, end) semantics: adjacency (one ends exactly when the other starts) is allowed."""
    return a_start < b_end and b_start < a_end


@bp.post("/exam-sessions")
def create_session():
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, SESSION_FIELDS)
    course_id = req_str(body, "course_id")
    room_name = req_str(body, "room_name")
    room_capacity = req_int(body, "room_capacity", positive=True)
    room_supports = opt_bool(body, "room_supports_accommodations", False)
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    if not end_at > start_at:
        raise_error(ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    course = require_ref("courses", course_id, "course_id")
    cycle = db["exam_cycles"][course["cycle_id"]]
    # Priority 6 state gates: cycle OPEN, course ACTIVE.
    if cycle["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "sessions require the cycle to be OPEN")
    if authorized_teacher_count(course["id"]) < 1:
        raise_error(ERR_TEACHER_NOT_AUTHORIZED,
                    "course has no AUTHORIZED teacher (course is SUSPENDED)")
    # Priority 7 safety: accommodation-capable room when any REGISTERED registration needs one.
    if not room_supports:
        for r in db["registrations"].values():
            if (r["course_id"] == course["id"] and r["registration_status"] == "REGISTERED"
                    and r["accommodation_type"] != "NONE"):
                raise_error(ERR_ROOM_NOT_ACCOMMODATION_CAPABLE,
                            "a REGISTERED registration requires accommodations but the "
                            "room does not support them")
    # Priority 8 temporal: window containment, then room half-open overlap.
    if start_at < cycle["exam_window_start_at"] or end_at > cycle["exam_window_end_at"]:
        raise_error(ERR_OUTSIDE_EXAM_WINDOW,
                    "session must start at/after exam_window_start_at and end at/before "
                    "exam_window_end_at")
    for s in db["exam_sessions"].values():
        if (s["room_name"] == room_name and s["status"] != "CANCELLED"
                and _half_open_overlap(start_at, end_at, s["start_at"], s["end_at"])):
            raise_error(ERR_ROOM_CONFLICT,
                        f"room {room_name} is already booked for an overlapping session")
    # Priority 9 uniqueness: one non-CANCELLED session per course.
    for s in db["exam_sessions"].values():
        if s["course_id"] == course["id"] and s["status"] != "CANCELLED":
            raise_error(ERR_DUPLICATE_SESSION,
                        "course already has a non-cancelled session")
    # Priority 9 quota: capacity must cover the course's REGISTERED count (equality fits).
    if room_capacity < course_seated_count(course["id"]):
        raise_error(ERR_ROOM_CAPACITY_INSUFFICIENT,
                    "room_capacity is below the course's REGISTERED registration count")
    rec = new_record("exam_sessions", {
        "course_id": course["id"],
        "room_name": room_name,
        "room_capacity": room_capacity,
        "room_supports_accommodations": room_supports,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    return success_object(serialize_session(rec), status=201)


@bp.get("/exam-sessions")
def list_sessions():
    require_roles(get_caller(), ALL_READ)
    filters = [
        ("course_id", request.args.get("course_id")),
        ("status", request.args.get("status")),
    ]
    return list_response(db["exam_sessions"].values(), filters, serialize_session)


@bp.get("/exam-sessions/<rid>")
def get_session(rid):
    require_roles(get_caller(), ALL_READ)
    session = require_path_resource("exam_sessions", rid)
    return success_object(serialize_session(session))


@bp.post("/exam-sessions/<rid>/administer")
def administer_session(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    session = require_path_resource("exam_sessions", rid)
    body = get_body()
    reject_unknown_fields(body, {"present_registration_ids"})
    ids = body.get("present_registration_ids")
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
        raise_error(ERR_INVALID_REQUEST,
                    "present_registration_ids must be an array of strings")
    # Priority 5: every listed id resolves.
    listed = []
    for reg_id in ids:
        reg = db["registrations"].get(reg_id)
        if reg is None:
            raise_error(ERR_REFERENCE_NOT_FOUND,
                        f"present_registration_ids id does not resolve: {reg_id}")
        listed.append(reg)
    # Priority 6 state: session SCHEDULED; each listed registration is of this
    # course and currently REGISTERED.
    if session["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"session in {session['status']} cannot be administered")
    for reg in listed:
        if reg["course_id"] != session["course_id"] or reg["registration_status"] != "REGISTERED":
            raise_error(ERR_INVALID_STATE,
                        "present_registration_ids must be REGISTERED registrations of "
                        "this session's course")
    # Priority 8 temporal: administer only at/after the session end.
    if CLOCK.now() < session["end_at"]:
        raise_error(ERR_SESSION_NOT_ENDED,
                    "the logical clock is before the session's end_at")
    listed_ids = {reg["id"] for reg in listed}
    for reg in db["registrations"].values():
        if reg["course_id"] != session["course_id"]:
            continue
        if reg["registration_status"] != "REGISTERED":
            continue
        if reg["id"] in listed_ids:
            reg["registration_status"] = "SAT"  # score_status stays PENDING
        else:
            reg["registration_status"] = "NO_SHOW"
            reg["score_status"] = "NO_SCORE"
        touch(reg)
    session["status"] = "ADMINISTERED"
    touch(session)
    return success_object(serialize_session(session))


@bp.post("/exam-sessions/<rid>/cancel")
def cancel_session(rid):
    require_roles(get_caller(), ["ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    session = require_path_resource("exam_sessions", rid)
    if session["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"session in {session['status']} cannot be cancelled")
    session["status"] = "CANCELLED"
    touch(session)
    # Release ASSIGNED proctor assignments; registrations are NOT cancelled.
    for pa in db["proctor_assignments"].values():
        if pa["session_id"] == session["id"] and pa["status"] == "ASSIGNED":
            pa["status"] = "RELEASED"
            touch(pa)
    return success_object(serialize_session(session))
