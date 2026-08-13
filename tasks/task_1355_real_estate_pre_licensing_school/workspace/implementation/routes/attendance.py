"""Attendance record endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination,
    check_instructor_scope, parse_date,
)
from response import success_object, success_list
from services.calculations import compute_seat_minutes, _extract_date

bp = Blueprint("attendance", __name__)


def _record_to_json(r):
    return {k: v for k, v in r.items()}


def _get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if not e:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND,
                           f"Enrollment {enrollment_id} not found")
    return e


def _get_record(record_id):
    r = db.attendance_records.get(record_id)
    if not r:
        errors.raise_error(errors.ERR_ATTENDANCE_RECORD_NOT_FOUND,
                           f"AttendanceRecord {record_id} not found")
    return r


def _recompute_enrollment_seat(enrollment):
    """Recompute seat minutes and auto-transition."""
    offering = db.offerings.get(enrollment["offering_id"])
    if not offering:
        return
    course = db.courses.get(offering["course_id"])
    if not course:
        return

    verified, creditable, frac = compute_seat_minutes(enrollment["id"], course)
    enrollment["verified_seat_minutes"] = verified
    enrollment["creditable_seat_minutes"] = creditable
    enrollment["completion_fraction_bps"] = frac

    # Auto-transitions
    if enrollment["academic_status"] == "ENROLLED" and verified > 0:
        old = enrollment["academic_status"]
        enrollment["academic_status"] = "IN_PROGRESS"
        db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                 "system", "system",
                 {"from_status": old, "to_status": "IN_PROGRESS"})

    if enrollment["academic_status"] == "IN_PROGRESS":
        if creditable >= course["required_seat_minutes"]:
            enrollment["academic_status"] = "SEAT_TIME_MET"
            db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": "IN_PROGRESS", "to_status": "SEAT_TIME_MET"})
    elif enrollment["academic_status"] == "SEAT_TIME_MET":
        if creditable < course["required_seat_minutes"]:
            enrollment["academic_status"] = "IN_PROGRESS"
            db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                     "system", "system",
                     {"from_status": "SEAT_TIME_MET", "to_status": "IN_PROGRESS"})

    db.touch(enrollment)


@bp.route("/enrollments/<enrollment_id>/attendance-records", methods=["POST"])
@require_roles("Instructor")
def create_attendance(enrollment_id):
    enrollment = _get_enrollment(enrollment_id)
    auth = request.auth

    # Scope: instructor must be the offering's instructor
    offering = db.offerings.get(enrollment["offering_id"])
    if not offering:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND, "Offering not found")
    check_instructor_scope(offering["instructor_id"], auth)

    body = get_json_body(required_fields=["session_date", "minutes"])

    # Validate minutes
    minutes = body["minutes"]
    if not isinstance(minutes, int) or isinstance(minutes, bool):
        errors.raise_error(errors.ERR_ATTENDANCE_MINUTES_INVALID,
                           "minutes must be an integer")
    if minutes < 1 or minutes > 1440:
        errors.raise_error(errors.ERR_ATTENDANCE_MINUTES_INVALID,
                           "minutes must be 1..1440")

    session_date = parse_date(body["session_date"], "session_date")

    # State: enrollment must be ENROLLED, IN_PROGRESS, or SEAT_TIME_MET
    if enrollment["academic_status"] not in ("ENROLLED", "IN_PROGRESS", "SEAT_TIME_MET"):
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Cannot record attendance in state {enrollment['academic_status']}")

    # Temporal: session_date within [offering.start_date, offering.end_date]
    o_start = _extract_date(offering["start_date"])
    o_end = _extract_date(offering["end_date"])
    if o_start and o_end:
        if session_date < o_start or session_date > o_end:
            errors.raise_error(errors.ERR_ATTENDANCE_OUT_OF_WINDOW,
                               "session_date outside offering window")

    record = db.new_entity({
        "enrollment_id": enrollment_id,
        "session_date": body["session_date"],
        "minutes": minutes,
        "recorded_by_instructor_id": auth["user_id"],
        "status": "VERIFIED",
    })
    db.attendance_records[record["id"]] = record
    db.audit("AttendanceRecord", record["id"], "ATTENDANCE_RECORDED",
             auth["role"], auth["user_id"])

    _recompute_enrollment_seat(enrollment)

    return success_object(_record_to_json(record), 201)


@bp.route("/enrollments/<enrollment_id>/attendance-records", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Instructor", "Student")
def list_attendance(enrollment_id):
    enrollment = _get_enrollment(enrollment_id)
    auth = request.auth

    # Student scope
    if auth["role"] == "Student":
        if enrollment["student_id"] != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own enrollment")

    # Instructor scope
    if auth["role"] == "Instructor":
        offering = db.offerings.get(enrollment["offering_id"])
        if offering and offering["instructor_id"] != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own offering")

    limit, offset = parse_pagination()
    items = [r for r in db.attendance_records.values() if r["enrollment_id"] == enrollment_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_record_to_json(r) for r in page], limit, offset, total)


@bp.route("/attendance-records/<id>/void", methods=["POST"])
@require_roles("Instructor")
def void_attendance(id):
    record = _get_record(id)
    auth = request.auth

    # Scope: instructor must be the offering's instructor
    enrollment = db.enrollments.get(record["enrollment_id"])
    if not enrollment:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    offering = db.offerings.get(enrollment["offering_id"])
    if not offering:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND, "Offering not found")
    check_instructor_scope(offering["instructor_id"], auth)

    # State: record must be VERIFIED
    if record["status"] != "VERIFIED":
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Record status is {record['status']}")

    # State: enrollment must not be EXAM_PASSED or COMPLETED
    if enrollment["academic_status"] in ("EXAM_PASSED", "COMPLETED"):
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           "Cannot void attendance after EXAM_PASSED")

    record["status"] = "VOID"
    db.touch(record)
    db.audit("AttendanceRecord", record["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "VERIFIED", "to_status": "VOID"})

    _recompute_enrollment_seat(enrollment)

    return success_object(_record_to_json(record))
