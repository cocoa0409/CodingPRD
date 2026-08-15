"""Class sections, enrollments, attendance records."""
from flask import Blueprint, g, request

from auth import authenticate, require_roles, ROLES
from db import db, Rec, stamp_new, stamp_new_appendonly, bump, prog_param
from errors import (err_not_found, err_forbidden, err_invalid_request,
                    err_invalid_state, err_stale_version, conflict)
from services import (ser_section, ser_enrollment, ser_attendance,
                      check_accreditation, eligible_active_screening,
                      run_promotion_selector, maybe_advance_to_pipeline,
                      recompute_attendance, midterm_revoke_check)
from util import (json_body, success_obj, paginate, v_str, v_int, v_enum)

bp = Blueprint("classes", __name__)

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
OUTCOMES = ("PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")
LIVE_ENROLLMENT_STATUSES = ("ENROLLED", "WAITLISTED", "PENDING_PROMOTION")


def _get_section(section_id):
    s = db.sections.get(section_id)
    if s is None:
        raise err_not_found("Class section not found")
    return s


def _get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise err_not_found("Enrollment not found")
    return e


# --------------------------- Class sections ---------------------------

@bp.post("/naturalization/class-sections")
def create_section():
    body = json_body()
    title = v_str(body, "title")
    weekday = v_enum(body, "weekday", WEEKDAYS)
    start_minute = v_int(body, "start_minute", minv=0)
    end_minute = v_int(body, "end_minute", minv=0)
    if end_minute <= start_minute:
        raise err_invalid_request("end_minute must be later than start_minute")
    room_id = v_str(body, "room_id")
    instructor_id = v_str(body, "instructor_volunteer_id")
    capacity = v_int(body, "capacity", minv=1)
    total_sessions = v_int(body, "total_sessions", minv=2)
    authenticate()
    require_roles("ProgramAdmin")
    instructor = db.volunteers.get(instructor_id)
    if instructor is None:
        raise err_not_found("Instructor volunteer not found")
    check_accreditation(instructor, "GENERAL_OR_LEGAL")
    for other in db.sections.values():
        if other.weekday == weekday and other.room_id == room_id:
            if start_minute < other.end_minute and other.start_minute < end_minute:
                raise conflict("ERR_SCHEDULE_CONFLICT",
                               "Room window overlaps an existing section")
    s = Rec(title=title, weekday=weekday, start_minute=start_minute,
            end_minute=end_minute, room_id=room_id,
            instructor_volunteer_id=instructor_id, capacity=capacity,
            total_sessions=total_sessions, enrolled_count=0,
            pending_promotion_count=0, waitlisted_count=0)
    stamp_new(s)
    db.sections[s.id] = s
    return success_obj(ser_section(s), 201)


@bp.get("/naturalization/class-sections")
def list_sections():
    authenticate()
    require_roles(*ROLES)
    recs = list(db.sections.values())
    instructor = request.args.get("instructor_volunteer_id")
    if instructor is not None:
        recs = [s for s in recs if s.instructor_volunteer_id == instructor]
    return paginate(recs, ser_section)


@bp.get("/naturalization/class-sections/<section_id>")
def get_section(section_id):
    authenticate()
    require_roles(*ROLES)
    return success_obj(ser_section(_get_section(section_id)))


@bp.get("/naturalization/class-sections/<section_id>/enrollments")
def list_section_enrollments(section_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Volunteer")
    section = _get_section(section_id)
    recs = [e for e in db.enrollments.values() if e.class_section_id == section.id]
    return paginate(recs, ser_enrollment)


# --------------------------- Enrollments ---------------------------

@bp.post("/naturalization/enrollments")
def create_enrollment():
    body = json_body()
    applicant_id = v_str(body, "applicant_id")
    class_section_id = v_str(body, "class_section_id")
    expected_version = v_int(body, "expected_section_version")
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err_not_found("Applicant not found")
    section = db.sections.get(class_section_id)
    if section is None:
        raise err_not_found("Class section not found")
    if g.user_role == "Applicant" and applicant_id != g.user_id:
        raise err_forbidden("Applicants may only enroll themselves")
    eligible_active_screening(applicant)
    for e in db.enrollments.values():
        if e.applicant_id == applicant.id and e.class_section_id == section.id \
                and e.status in LIVE_ENROLLMENT_STATUSES:
            raise conflict("ERR_ENROLLMENT_DUPLICATE_ACTIVE",
                           "Applicant already holds a live enrollment in this section")
    if expected_version != section.version:
        raise err_stale_version()

    seats_open = section.capacity - section.enrolled_count - section.pending_promotion_count
    if seats_open >= 1:
        status = "ENROLLED"
    else:
        status = "WAITLISTED"
    e = Rec(applicant_id=applicant.id, class_section_id=section.id, status=status,
            attendance_bp=0, records_count=0, offer_expires_at=None)
    stamp_new(e)
    db.enrollments[e.id] = e
    if status == "ENROLLED":
        section.enrolled_count += 1
    else:
        section.waitlisted_count += 1
    bump(section)
    if status == "ENROLLED":
        maybe_advance_to_pipeline(applicant)
    return success_obj(ser_enrollment(e), 201)


@bp.get("/naturalization/enrollments")
def list_enrollments():
    authenticate()
    require_roles(*ROLES)
    recs = list(db.enrollments.values())
    if g.user_role == "Applicant":
        recs = [e for e in recs if e.applicant_id == g.user_id]
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        recs = [e for e in recs if e.applicant_id == applicant_id]
    section_id = request.args.get("class_section_id")
    if section_id is not None:
        recs = [e for e in recs if e.class_section_id == section_id]
    status = request.args.get("status")
    if status is not None:
        recs = [e for e in recs if e.status == status]
    return paginate(recs, ser_enrollment)


@bp.get("/naturalization/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    authenticate()
    require_roles(*ROLES)
    e = _get_enrollment(enrollment_id)
    if g.user_role == "Applicant" and e.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own enrollments")
    if g.user_role == "Volunteer":
        section = db.sections.get(e.class_section_id)
        if section is None or section.instructor_volunteer_id != g.user_id:
            raise err_forbidden("Volunteers may only read enrollments in own sections")
    return success_obj(ser_enrollment(e))


@bp.post("/naturalization/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    e = _get_enrollment(enrollment_id)
    if g.user_role == "Applicant" and e.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only withdraw their own enrollments")
    if e.status != "ENROLLED":
        raise err_invalid_state("Only an ENROLLED enrollment may be withdrawn")
    section = db.sections.get(e.class_section_id)
    e.status = "WITHDRAWN"
    bump(e)
    if section is not None:
        section.enrolled_count -= 1
        bump(section)
        run_promotion_selector(section)
    return success_obj(ser_enrollment(e))


@bp.post("/naturalization/enrollments/<enrollment_id>/confirm-promotion")
def confirm_promotion(enrollment_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    e = _get_enrollment(enrollment_id)
    if g.user_role == "Applicant" and e.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only confirm their own enrollments")
    if e.status != "PENDING_PROMOTION":
        raise err_invalid_state("Only a PENDING_PROMOTION enrollment may be confirmed")
    section = db.sections.get(e.class_section_id)
    e.status = "ENROLLED"
    e.offer_expires_at = None
    bump(e)
    if section is not None:
        section.pending_promotion_count -= 1
        section.enrolled_count += 1
        bump(section)
    applicant = db.applicants.get(e.applicant_id)
    if applicant is not None:
        maybe_advance_to_pipeline(applicant)
    return success_obj(ser_enrollment(e))


@bp.post("/naturalization/enrollments/<enrollment_id>/complete")
def complete_enrollment(enrollment_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator")
    e = _get_enrollment(enrollment_id)
    if e.status != "ENROLLED":
        raise err_invalid_state("Only an ENROLLED enrollment may be completed")
    section = db.sections.get(e.class_section_id)
    total_sessions = section.total_sessions if section is not None else 0
    if e.records_count != total_sessions:
        raise conflict("ERR_SESSIONS_INCOMPLETE",
                       "Attendance record log is incomplete")
    if e.attendance_bp < prog_param("attendance_complete_bp"):
        raise conflict("ERR_ATTENDANCE_BELOW_THRESHOLD",
                       "Attendance is below the completion threshold")
    e.status = "COMPLETED"
    bump(e)
    # Keep the ledger invariant exact: enrolled_count == count(ENROLLED rows).
    # Completion is not a promotion trigger (only withdraw / auto-revoke /
    # offer-expiry free seats for selection).
    if section is not None:
        section.enrolled_count -= 1
        bump(section)
    return success_obj(ser_enrollment(e))


# --------------------------- Attendance records ---------------------------

@bp.post("/naturalization/enrollments/<enrollment_id>/attendance-records")
def create_attendance(enrollment_id):
    body = json_body()
    session_index = v_int(body, "session_index", minv=1)
    outcome = v_enum(body, "outcome", OUTCOMES)
    authenticate()
    require_roles("Volunteer", "IntakeCoordinator")
    e = _get_enrollment(enrollment_id)
    section = db.sections.get(e.class_section_id)
    if g.user_role == "Volunteer":
        if section is None or section.instructor_volunteer_id != g.user_id:
            raise err_forbidden("Volunteers may only record attendance in own sections")
    if section is not None and session_index > section.total_sessions:
        raise err_invalid_request("session_index exceeds total_sessions")
    for r in db.attendance.values():
        if r.enrollment_id == e.id and r.session_index == session_index:
            raise conflict("ERR_SESSION_ALREADY_RECORDED",
                           "This session_index is already recorded")
    rec = Rec(enrollment_id=e.id, session_index=session_index, outcome=outcome)
    stamp_new_appendonly(rec)
    db.attendance[rec.id] = rec
    recompute_attendance(e)
    bump(e)
    if section is not None:
        midterm_revoke_check(e, section)
    return success_obj(ser_attendance(rec), 201)


@bp.get("/naturalization/enrollments/<enrollment_id>/attendance-records")
def list_attendance(enrollment_id):
    authenticate()
    require_roles(*ROLES)
    e = _get_enrollment(enrollment_id)
    if g.user_role == "Applicant" and e.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own attendance")
    recs = [r for r in db.attendance.values() if r.enrollment_id == e.id]
    return paginate(recs, ser_attendance)
