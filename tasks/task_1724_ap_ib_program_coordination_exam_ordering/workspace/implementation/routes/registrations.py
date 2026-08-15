"""ExamRegistration endpoints (PRD 3.3, 3.7): parallel registration/score dimensions."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_REGISTRATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_SCORE_BELOW_THRESHOLD,
    ERR_SESSION_FULL,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch
from services.derived import course_seated_count, scheduled_session_for_course
from services.serialize import serialize_registration
from util import CLOCK
from validate import (
    get_body, reject_unknown_fields, opt_enum, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("registrations", __name__)

ALL_READ = ["ApCoordinator", "Registrar", "Teacher", "Student"]
ACCOMMODATIONS = ("NONE", "EXTENDED_TIME", "SEPARATE_ROOM")


@bp.post("/registrations")
def create_registration():
    caller = require_roles(get_caller(), ["Student"])
    body = get_body()
    # Priority 2 ownership on the raw identity field, then full shape (priority 4).
    raw_sid = body.get("student_id")
    if isinstance(raw_sid, str) and raw_sid != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "student_id must equal the caller's X-User-ID")
    reject_unknown_fields(body, {"student_id", "course_id", "accommodation_type"})
    student_id = req_str(body, "student_id")
    course_id = req_str(body, "course_id")
    accommodation_type = opt_enum(body, "accommodation_type", ACCOMMODATIONS, "NONE")
    if student_id != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "student_id must equal the caller's X-User-ID")
    student = require_ref("students", student_id, "student_id")
    course = require_ref("courses", course_id, "course_id")
    cycle = db["exam_cycles"][course["cycle_id"]]
    # Priority 6 state gate: the course's cycle must be OPEN.
    if cycle["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "registrations require the cycle to be OPEN")
    # Priority 9 uniqueness: one non-CANCELLED registration per (student, course).
    for r in db["registrations"].values():
        if (r["student_id"] == student["id"] and r["course_id"] == course["id"]
                and r["registration_status"] != "CANCELLED"):
            raise_error(ERR_DUPLICATE_REGISTRATION,
                        "student already has a non-cancelled registration for this course")
    # Priority 9 quota: must fit the SCHEDULED session's remaining capacity.
    session = scheduled_session_for_course(course["id"])
    if session is not None and course_seated_count(course["id"]) + 1 > session["room_capacity"]:
        raise_error(ERR_SESSION_FULL,
                    "registration would exceed the scheduled session's room capacity")
    now = CLOCK.now()
    is_late = now > cycle["registration_deadline_at"]  # strictly after; AT is on time
    rec = new_record("registrations", {
        "student_id": student["id"],
        "course_id": course["id"],
        "cycle_id": course["cycle_id"],
        "accommodation_type": accommodation_type,
        "registration_status": "REGISTERED",
        "score_status": "PENDING",
        "score": None,
        "is_late": is_late,
        "fee_cents": course["exam_fee_cents"],
        "late_fee_applied_cents": cycle["late_fee_cents"] if is_late else 0,
    })
    return success_object(serialize_registration(rec), status=201)


@bp.get("/registrations")
def list_registrations():
    caller = require_roles(get_caller(), ALL_READ)
    student_filter = request.args.get("student_id")
    if caller.role == "Student":
        student_filter = caller.user_id
    filters = [
        ("student_id", student_filter),
        ("course_id", request.args.get("course_id")),
        ("cycle_id", request.args.get("cycle_id")),
        ("registration_status", request.args.get("registration_status")),
        ("score_status", request.args.get("score_status")),
    ]
    return list_response(db["registrations"].values(), filters, serialize_registration)


@bp.get("/registrations/<rid>")
def get_registration(rid):
    caller = require_roles(get_caller(), ALL_READ)
    reg = require_path_resource("registrations", rid)
    if caller.role == "Student" and reg["student_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "students may only read their own registrations")
    return success_object(serialize_registration(reg))


@bp.post("/registrations/<rid>/cancel")
def cancel_registration(rid):
    caller = require_roles(get_caller(), ["Student", "ApCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    reg = require_path_resource("registrations", rid)
    if caller.role == "Student" and reg["student_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN,
                    "students may only cancel their own registrations")
    if reg["registration_status"] != "REGISTERED":
        raise_error(ERR_INVALID_STATE,
                    f"registration in {reg['registration_status']} cannot be cancelled")
    reg["registration_status"] = "CANCELLED"
    reg["score_status"] = "VOID"
    touch(reg)
    return success_object(serialize_registration(reg))


@bp.post("/registrations/<rid>/post-to-transcript")
def post_to_transcript(rid):
    require_roles(get_caller(), ["Registrar"])
    body = get_body()
    reject_unknown_fields(body, set())
    reg = require_path_resource("registrations", rid)
    if reg["score_status"] != "RELEASED":
        raise_error(ERR_INVALID_STATE,
                    f"score_status {reg['score_status']} cannot be posted; RELEASED required")
    course = db["courses"][reg["course_id"]]
    if reg["score"] < course["credit_threshold"]:
        raise_error(ERR_SCORE_BELOW_THRESHOLD,
                    f"score {reg['score']} below credit threshold {course['credit_threshold']}")
    reg["score_status"] = "POSTED"
    touch(reg)
    return success_object(serialize_registration(reg))
