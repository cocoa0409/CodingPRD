"""Mock interviews: booking, scoring, no-show, cancel."""
from datetime import timedelta

from flask import Blueprint, g, request

from auth import authenticate, require_roles, ROLES
from db import db, Rec, stamp_new, bump, prog_param
from errors import err_not_found, err_forbidden, err_invalid_state, conflict
from services import (ser_mock, check_accreditation, attained_readiness_score)
from util import (json_body, success_obj, paginate, v_str, v_int, v_datetime)

bp = Blueprint("mocks", __name__)


def _get_mock(interview_id):
    m = db.mocks.get(interview_id)
    if m is None:
        raise err_not_found("Mock interview not found")
    return m


@bp.post("/naturalization/mock-interviews")
def create_mock():
    body = json_body()
    applicant_id = v_str(body, "applicant_id")
    volunteer_id = v_str(body, "volunteer_id")
    raw_start, dt_start = v_datetime(body, "scheduled_start")
    duration = v_int(body, "duration_minutes", required=False, minv=10)
    if duration is None:
        duration = 30
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err_not_found("Applicant not found")
    volunteer = db.volunteers.get(volunteer_id)
    if volunteer is None:
        raise err_not_found("Volunteer not found")
    if g.user_role == "Applicant" and applicant_id != g.user_id:
        raise err_forbidden("Applicants may only book interviews for themselves")
    check_accreditation(volunteer, "GENERAL_OR_LEGAL")
    # Turnaround buffer: gap >= mock_buffer_minutes vs every non-cancelled
    # interview of this volunteer.
    buffer = timedelta(minutes=prog_param("mock_buffer_minutes"))
    new_end = dt_start + timedelta(minutes=duration)
    for m in db.mocks.values():
        if m.volunteer_id != volunteer.id or m.status == "CANCELLED":
            continue
        ex_start = m.scheduled_start_dt
        ex_end = ex_start + timedelta(minutes=m.duration_minutes)
        if dt_start >= ex_end:
            gap = dt_start - ex_end
        elif ex_start >= new_end:
            gap = ex_start - new_end
        else:
            gap = timedelta(minutes=-1)
        if gap < buffer:
            raise conflict("ERR_INTERVIEW_SLOT_CONFLICT",
                           "Insufficient gap from another interview")
    attempts = sum(1 for m in db.mocks.values()
                   if m.applicant_id == applicant.id and m.status != "CANCELLED")
    if attempts >= prog_param("mock_max_attempts"):
        raise conflict("ERR_MOCK_ATTEMPTS_EXHAUSTED",
                       "Applicant has exhausted mock interview attempts")
    has_completed = any(e.applicant_id == applicant.id and e.status == "COMPLETED"
                        for e in db.enrollments.values())
    if not has_completed and attained_readiness_score(applicant) < 40:
        raise conflict("ERR_MOCK_ELIGIBILITY",
                       "No COMPLETED enrollment and attained readiness below 40")
    m = Rec(applicant_id=applicant.id, volunteer_id=volunteer.id,
            scheduled_start_raw=raw_start, scheduled_start_dt=dt_start,
            duration_minutes=duration, status="SCHEDULED",
            english_pct=None, civics_pct=None, n400_pct=None,
            overall_score=None, outcome=None)
    stamp_new(m)
    db.mocks[m.id] = m
    return success_obj(ser_mock(m), 201)


@bp.get("/naturalization/mock-interviews")
def list_mocks():
    authenticate()
    require_roles(*ROLES)
    recs = list(db.mocks.values())
    if g.user_role == "Applicant":
        recs = [m for m in recs if m.applicant_id == g.user_id]
    for field in ("applicant_id", "volunteer_id", "status"):
        val = request.args.get(field)
        if val is not None:
            recs = [m for m in recs if getattr(m, field) == val]
    return paginate(recs, ser_mock)


@bp.get("/naturalization/mock-interviews/<interview_id>")
def get_mock(interview_id):
    authenticate()
    require_roles(*ROLES)
    m = _get_mock(interview_id)
    if g.user_role == "Applicant" and m.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own interviews")
    return success_obj(ser_mock(m))


@bp.post("/naturalization/mock-interviews/<interview_id>/score")
def score_mock(interview_id):
    body = json_body()
    english = v_int(body, "english_pct", minv=0, maxv=100)
    civics = v_int(body, "civics_pct", minv=0, maxv=100)
    n400 = v_int(body, "n400_pct", minv=0, maxv=100)
    authenticate()
    require_roles("Volunteer")
    m = _get_mock(interview_id)
    if m.volunteer_id != g.user_id:
        raise err_forbidden("Only the assigned volunteer may score this interview")
    if m.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview may be scored")
    overall = (40 * english + 40 * civics + 20 * n400) // 100
    m.english_pct = english
    m.civics_pct = civics
    m.n400_pct = n400
    m.overall_score = overall
    m.outcome = "PASS" if (overall >= 70 and civics >= 60) else "NEEDS_RETRY"
    m.status = "COMPLETED"
    bump(m)
    return success_obj(ser_mock(m))


@bp.post("/naturalization/mock-interviews/<interview_id>/no-show")
def no_show_mock(interview_id):
    json_body()
    authenticate()
    require_roles("Volunteer", "IntakeCoordinator")
    m = _get_mock(interview_id)
    if g.user_role == "Volunteer" and m.volunteer_id != g.user_id:
        raise err_forbidden("Only the assigned volunteer may mark a no-show")
    if m.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview may be marked no-show")
    m.status = "NO_SHOW"
    bump(m)
    return success_obj(ser_mock(m))


@bp.post("/naturalization/mock-interviews/<interview_id>/cancel")
def cancel_mock(interview_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    m = _get_mock(interview_id)
    if g.user_role == "Applicant" and m.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only cancel their own interviews")
    if m.status != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview may be cancelled")
    m.status = "CANCELLED"
    bump(m)
    return success_obj(ser_mock(m))
