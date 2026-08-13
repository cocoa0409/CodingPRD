"""Exam session and test registration endpoints."""
from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import ser_exam_session, ser_test_registration
from services import core
from services import coop as coop_svc
from services import testing as testing_svc
from validation import (
    get_body, req_string, req_date, req_datetime, req_int, req_enum,
    opt_string, req_int_list, ATTENDANCE_OUTCOMES,
)

bp = Blueprint("exams", __name__)

_SESSION_CHAIN = (("exam_session", "session_id", db.exam_sessions),)
_REG_CHAIN = (("test_registration", "registration_id", db.test_registrations),)

EXAM_BUFFER_MINUTES = 30


@bp.route("/academic-years/<year_id>/exam-sessions", methods=["POST"])
@route(["Registrar"], parent_chain=(("academic_year", "year_id", db.academic_years),))
def create_session(year_id):
    body = get_body()
    test_name = req_string(body, "test_name")
    session_date = req_date(body, "session_date")
    start_minutes = req_int(body, "start_minutes", lo=0, hi=1439)
    end_minutes = req_int(body, "end_minutes", lo=0, hi=1440)
    if end_minutes <= start_minutes:
        raise_err("ERR_INVALID_REQUEST", "end_minutes must be > start_minutes")
    capacity = req_int(body, "capacity", lo=1)
    registration_deadline = req_datetime(body, "registration_deadline")
    target_grades = req_int_list(body, "target_grades", lo=0, hi=12)
    location = opt_string(body, "location")

    rec = core.make_record({
        "academic_year_id": year_id,
        "test_name": test_name,
        "session_date": session_date,
        "start_minutes": start_minutes,
        "end_minutes": end_minutes,
        "capacity": capacity,
        "registration_deadline": registration_deadline,
        "target_grades": list(target_grades),
        "location": location,
        "seats_taken": 0,
        "status": "SCHEDULED",
    })
    db.exam_sessions[rec["id"]] = rec
    return success_object(ser_exam_session(rec), status=201)


@bp.route("/exam-sessions/<session_id>", methods=["GET"])
@route(ALL_ROLES, parent_chain=_SESSION_CHAIN)
def get_session(session_id):
    return success_object(ser_exam_session(db.exam_sessions[session_id]))


@bp.route("/exam-sessions/<session_id>/open-registration", methods=["POST"])
@route(["Registrar"], parent_chain=_SESSION_CHAIN)
def open_registration(session_id):
    sess = db.exam_sessions[session_id]
    if sess["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Session is not SCHEDULED")
    year = core.year_of_exam_session(sess)
    if year["status"] != "OPEN":
        raise_err("ERR_ACADEMIC_YEAR_NOT_OPEN", "Academic year is not OPEN")
    sess["status"] = "REGISTRATION_OPEN"
    core.touch(sess)
    return success_object(ser_exam_session(sess))


@bp.route("/exam-sessions/<session_id>/close-registration", methods=["POST"])
@route(["Registrar"], parent_chain=_SESSION_CHAIN)
def close_registration(session_id):
    sess = db.exam_sessions[session_id]
    if sess["status"] != "REGISTRATION_OPEN":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Session is not REGISTRATION_OPEN")
    sess["status"] = "REGISTRATION_CLOSED"
    core.touch(sess)
    return success_object(ser_exam_session(sess))


@bp.route("/exam-sessions/<session_id>/administer", methods=["POST"])
@route(["Registrar"], parent_chain=_SESSION_CHAIN)
def administer_session(session_id):
    sess = db.exam_sessions[session_id]
    if sess["status"] != "REGISTRATION_CLOSED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Session is not REGISTRATION_CLOSED")
    sess["status"] = "ADMINISTERED"
    core.touch(sess)
    return success_object(ser_exam_session(sess))


@bp.route("/exam-sessions/<session_id>/registrations", methods=["GET"])
@route(ALL_ROLES, parent_chain=_SESSION_CHAIN)
def list_session_registrations(session_id):
    recs = [r for r in db.test_registrations.values()
            if r["exam_session_id"] == session_id]
    status = request.args.get("status")
    if status:
        recs = [r for r in recs if r["status"] == status]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_test_registration(r) for r in page], limit, offset, total)


def _check_exam_buffer(enrollment_id, new_session):
    """30-minute buffer against the student's other same-date sittings."""
    for reg in db.test_registrations.values():
        if reg["enrollment_id"] != enrollment_id:
            continue
        if reg["status"] not in ("REGISTERED", "ATTENDED", "SCORED"):
            continue
        other = db.exam_sessions.get(reg["exam_session_id"])
        if other is None or other["id"] == new_session["id"]:
            continue
        if other["session_date"] != new_session["session_date"]:
            continue
        gap1 = new_session["start_minutes"] - other["end_minutes"]
        gap2 = other["start_minutes"] - new_session["end_minutes"]
        if max(gap1, gap2) < EXAM_BUFFER_MINUTES:
            raise_err("ERR_EXAM_SCHEDULE_CONFLICT",
                      "Sitting violates the 30-minute buffer against another session")


@bp.route("/exam-sessions/<session_id>/registrations", methods=["POST"])
@route(["Parent"], parent_chain=_SESSION_CHAIN)
def create_registration(session_id):
    sess = db.exam_sessions[session_id]
    body = get_body()
    enrollment_id = req_string(body, "enrollment_id")
    en = db.enrollments.get(enrollment_id)
    if en is None:
        raise_err("ERR_NOT_FOUND", f"enrollment {enrollment_id} not found")
    # Parent ownership on the referenced enrollment
    if request.user_role == "Parent":
        owner = core.root_family_id("enrollment", enrollment_id)
        if owner is not None and request.user_id != owner:
            raise_err("ERR_OWNERSHIP_MISMATCH",
                      "Parent may only register own family's enrollment")
    if sess["status"] != "REGISTRATION_OPEN":
        raise_err("ERR_EXAM_SESSION_NOT_OPEN",
                  "Registration requires REGISTRATION_OPEN")
    if en["compliance_standing"] == "NONCOMPLIANT":
        raise_err("ERR_ENROLLMENT_NONCOMPLIANT",
                  "NONCOMPLIANT enrollments may not register for exams")
    if clock.now() > clock.parse(sess["registration_deadline"]):
        raise_err("ERR_EXAM_REGISTRATION_DEADLINE_PASSED",
                  "Registration deadline has passed")
    if en["grade_level"] not in sess["target_grades"]:
        raise_err("ERR_EXAM_GRADE_MISMATCH",
                  "Enrollment grade is not a target grade for this session")
    _check_exam_buffer(enrollment_id, sess)
    if sess["seats_taken"] >= sess["capacity"]:
        raise_err("ERR_EXAM_SESSION_FULL", "Session has no free seats")

    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "exam_session_id": session_id,
        "status": "REGISTERED",
        "composite_percentile": None,
        "passed": None,
        "exemption_note": None,
    })
    db.test_registrations[rec["id"]] = rec
    sess["seats_taken"] += 1
    core.touch(sess)
    return success_object(ser_test_registration(rec), status=201)


@bp.route("/test-registrations/<registration_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("test_registration", "registration_id"),
       parent_chain=_REG_CHAIN)
def get_registration(registration_id):
    return success_object(ser_test_registration(db.test_registrations[registration_id]))


@bp.route("/test-registrations/<registration_id>/cancel", methods=["POST"])
@route(["Parent", "Registrar"], ownership=("test_registration", "registration_id"),
       parent_chain=_REG_CHAIN)
def cancel_registration(registration_id):
    reg = db.test_registrations[registration_id]
    if reg["status"] != "REGISTERED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only REGISTERED registrations may be cancelled")
    sess = db.exam_sessions.get(reg["exam_session_id"])
    if sess["status"] not in ("SCHEDULED", "REGISTRATION_OPEN", "REGISTRATION_CLOSED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Session no longer accepts cancellations")
    reg["status"] = "CANCELLED"
    core.touch(reg)
    sess["seats_taken"] -= 1
    core.touch(sess)
    return success_object(ser_test_registration(reg))


@bp.route("/test-registrations/<registration_id>/record-attendance", methods=["POST"])
@route(["Registrar"], parent_chain=_REG_CHAIN)
def record_attendance(registration_id):
    reg = db.test_registrations[registration_id]
    body = get_body()
    outcome = req_enum(body, "attendance_outcome", ATTENDANCE_OUTCOMES)
    exemption_note = opt_string(body, "exemption_note")
    if reg["status"] != "REGISTERED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only REGISTERED registrations accept attendance recording")
    sess = db.exam_sessions.get(reg["exam_session_id"])
    if sess["status"] != "ADMINISTERED":
        raise_err("ERR_EXAM_SESSION_NOT_OPEN",
                  "Attendance recording requires an ADMINISTERED session")
    if outcome == "EXCUSED" and (exemption_note is None or exemption_note == ""):
        raise_err("ERR_INVALID_REQUEST",
                  "exemption_note is required when attendance_outcome is EXCUSED")

    en = db.enrollments.get(reg["enrollment_id"])
    reg["status"] = outcome
    if outcome == "EXCUSED":
        reg["exemption_note"] = exemption_note
    core.touch(reg)

    if outcome == "EXCUSED" and en is not None:
        testing_svc.recompute_testing_satisfied(en)
    if outcome == "NO_SHOW" and en is not None and en["testing_required"]:
        if not en["standing_locked"] and en["compliance_standing"] != "NONCOMPLIANT":
            en["compliance_standing"] = "NONCOMPLIANT"
            core.touch(en)
            coop_svc.noncompliant_cascade(en)
    return success_object(ser_test_registration(reg))


@bp.route("/test-registrations/<registration_id>/record-score", methods=["POST"])
@route(["Registrar"], parent_chain=_REG_CHAIN)
def record_score(registration_id):
    reg = db.test_registrations[registration_id]
    body = get_body()
    percentile = req_int(body, "composite_percentile", lo=1, hi=99)
    if reg["status"] != "ATTENDED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only ATTENDED registrations may be scored")
    reg["composite_percentile"] = percentile
    reg["passed"] = percentile >= testing_svc.PASSING_PERCENTILE
    reg["status"] = "SCORED"
    core.touch(reg)
    en = db.enrollments.get(reg["enrollment_id"])
    if en is not None:
        testing_svc.recompute_testing_satisfied(en)
    return success_object(ser_test_registration(reg))
