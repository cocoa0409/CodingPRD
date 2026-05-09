"""LiveClass + Attendance endpoints."""
import secrets
import string

from flask import Blueprint, request

from db import bump, make_common_fields, make_immutable_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services.lookup import (
    get_chapter,
    get_course,
    get_enrollment,
    get_instructor,
    get_live_class,
    get_student,
)
from services.progress import recompute_progress

live_classes_bp = Blueprint("live_classes", __name__)

ROOM_BUFFER_SECONDS = 600
CHECKIN_OPEN_LEAD_SECONDS = 900
LATE_BOUNDARY_SECONDS = 1800


def _alnum6():
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


def _check_room_overlap(room_id, start_ts, end_ts, exclude_id=None):
    for lc in store.live_classes.values():
        if exclude_id and lc["id"] == exclude_id:
            continue
        if lc["room_id"] != room_id:
            continue
        if lc["status"] not in ("SCHEDULED", "LIVE"):
            continue
        occ_start = int(lc["start_ts"])
        occ_end = int(lc["end_ts"]) + ROOM_BUFFER_SECONDS
        if start_ts < occ_end and end_ts > occ_start:
            raise_api("ERR_ROOM_CONFLICT", "Room conflict")


def _check_instructor_availability(instructor_id, start_ts, end_ts):
    instructor = get_instructor(instructor_id)
    for w in instructor.get("availability_windows", []):
        if int(w["start_ts"]) <= start_ts and end_ts <= int(w["end_ts"]):
            return
    raise_api("ERR_INSTRUCTOR_UNAVAILABLE", "Instructor unavailable")


@live_classes_bp.route("/courses/<course_id>/live-classes", methods=["POST"])
def create_live_class(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    body = request.get_json(silent=True) or {}

    chapter_id = body.get("chapter_id")
    if chapter_id:
        ch = get_chapter(chapter_id)
        if ch["course_id"] != course_id:
            raise_api("ERR_CHAPTER_NOT_FOUND", "Chapter not under this course")
    instructor_id = body.get("instructor_id") or user_id
    get_instructor(instructor_id)
    room_id = body.get("room_id")
    if not room_id:
        raise_api("ERR_INVALID_PRICING", "room_id required")
    try:
        start_ts = int(body["start_ts"])
        end_ts = int(body["end_ts"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "start_ts/end_ts required")
    if end_ts <= start_ts:
        raise_api("ERR_INVALID_PRICING", "end_ts must be > start_ts")

    # Room conflict (priority 8) BEFORE instructor availability (priority 9)
    _check_room_overlap(room_id, start_ts, end_ts)
    _check_instructor_availability(instructor_id, start_ts, end_ts)

    rec = body.get("recording_playback_enabled")
    if not isinstance(rec, bool):
        rec = True
    lc = {
        **make_common_fields(),
        "course_id": course_id,
        "chapter_id": chapter_id,
        "instructor_id": instructor_id,
        "room_id": room_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "status": "SCHEDULED",
        "checkin_code": None,
        "recording_playback_enabled": rec,
        "original_live_class_id": None,
    }
    store.live_classes[lc["id"]] = lc
    return success(dict(lc), http_status=201)


@live_classes_bp.route("/live-classes/<lc_id>/start", methods=["POST"])
def start_live_class(lc_id):
    user_id, _ = require_roles("Instructor")
    lc = get_live_class(lc_id)
    course = store.courses.get(lc["course_id"])
    if not course:
        raise_api("ERR_COURSE_NOT_FOUND", "Parent course missing")
    if lc["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the live class instructor")
    if lc["status"] != "SCHEDULED":
        raise_api("ERR_LIVE_CLASS_NOT_SCHEDULED", "LiveClass must be SCHEDULED")
    if course.get("posture") == "FROZEN":
        raise_api("ERR_COURSE_FROZEN", "Course is frozen")
    if store.clock_now_ts < int(lc["start_ts"]) - 600:
        raise_api("ERR_LIVE_CLASS_TOO_EARLY", "Too early to start")
    lc["status"] = "LIVE"
    lc["checkin_code"] = _alnum6()
    bump(lc)
    return success(dict(lc))


@live_classes_bp.route("/live-classes/<lc_id>/end", methods=["POST"])
def end_live_class(lc_id):
    user_id, _ = require_roles("Instructor")
    lc = get_live_class(lc_id)
    if lc["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the live class instructor")
    if lc["status"] != "LIVE":
        raise_api("ERR_LIVE_CLASS_NOT_LIVE", "LiveClass must be LIVE")
    lc["status"] = "ENDED"
    bump(lc)
    # Autofill ABSENT for any enrollment without an Attendance row
    enrollments = [e for e in store.enrollments.values() if e["course_id"] == lc["course_id"]]
    existing = {a["enrollment_id"] for a in store.attendances.values() if a["live_class_id"] == lc_id}
    for enr in enrollments:
        if enr["id"] in existing:
            continue
        att = {
            **make_immutable_fields(),
            "live_class_id": lc_id,
            "enrollment_id": enr["id"],
            "mark": "ABSENT",
            "checkin_method": "TIME_WINDOW",
            "checkin_ts": None,
            "code_provided": None,
        }
        store.attendances[att["id"]] = att
    # Recompute progress for enrollments in this course
    for enr in enrollments:
        recompute_progress(enr, run_at_risk=True)
    return success(dict(lc))


@live_classes_bp.route("/live-classes/<lc_id>/reschedule", methods=["POST"])
def reschedule_live_class(lc_id):
    user_id, _ = require_roles("Instructor")
    lc = get_live_class(lc_id)
    if lc["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the live class instructor")
    if lc["status"] != "SCHEDULED":
        raise_api("ERR_LIVE_CLASS_NOT_SCHEDULED", "LiveClass must be SCHEDULED")
    body = request.get_json(silent=True) or {}
    room_id = body.get("room_id")
    if not room_id:
        raise_api("ERR_INVALID_PRICING", "room_id required")
    try:
        start_ts = int(body["start_ts"])
        end_ts = int(body["end_ts"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "start_ts/end_ts required")
    if end_ts <= start_ts:
        raise_api("ERR_INVALID_PRICING", "end_ts must be > start_ts")
    # Mark original first as RESCHEDULED so its time slot is freed
    lc["status"] = "RESCHEDULED"
    bump(lc)
    try:
        _check_room_overlap(room_id, start_ts, end_ts, exclude_id=lc_id)
        _check_instructor_availability(lc["instructor_id"], start_ts, end_ts)
    except Exception:
        # Restore on failure
        lc["status"] = "SCHEDULED"
        bump(lc)
        raise
    new_lc = {
        **make_common_fields(),
        "course_id": lc["course_id"],
        "chapter_id": lc.get("chapter_id"),
        "instructor_id": lc["instructor_id"],
        "room_id": room_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "status": "SCHEDULED",
        "checkin_code": None,
        "recording_playback_enabled": lc.get("recording_playback_enabled", True),
        "original_live_class_id": lc["id"],
    }
    store.live_classes[new_lc["id"]] = new_lc
    return success(dict(new_lc), http_status=201)


@live_classes_bp.route("/live-classes/<lc_id>/check-in", methods=["POST"])
def check_in(lc_id):
    user_id, _ = require_roles("Student")
    lc = get_live_class(lc_id)
    if lc["status"] != "LIVE":
        raise_api("ERR_LIVE_CLASS_NOT_LIVE", "LiveClass must be LIVE for check-in")
    body = request.get_json(silent=True) or {}
    method = body.get("checkin_method")
    if method not in ("TIME_WINDOW", "CODE", "FACE", "LEAVE"):
        raise_api("ERR_INVALID_PRICING", "Invalid checkin_method")
    try:
        checkin_ts = int(body["checkin_ts"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "checkin_ts required")
    code_provided = body.get("code_provided")

    # Find caller's enrollment for this course
    enrollment = None
    for e in store.enrollments.values():
        if e["course_id"] == lc["course_id"] and e["student_id"] == user_id:
            enrollment = e
            break
    if not enrollment:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "No enrollment for this course")

    delta = checkin_ts - int(lc["start_ts"])
    if delta < -CHECKIN_OPEN_LEAD_SECONDS:
        raise_api("ERR_CHECKIN_WINDOW_CLOSED", "Too early")
    if delta <= 0:
        mark = "ATTENDED"
    elif delta <= LATE_BOUNDARY_SECONDS:
        mark = "LATE"
    else:
        raise_api("ERR_CHECKIN_WINDOW_CLOSED", "Too late")

    att = {
        **make_immutable_fields(),
        "live_class_id": lc_id,
        "enrollment_id": enrollment["id"],
        "mark": mark,
        "checkin_method": method,
        "checkin_ts": checkin_ts,
        "code_provided": code_provided,
    }
    store.attendances[att["id"]] = att
    recompute_progress(enrollment, run_at_risk=True)
    return success(dict(att), http_status=201)
