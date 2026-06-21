"""Participant endpoints: create, get, list, enroll, attendance-summary.
PRD §3.2, §3.4, §3.7."""
from flask import request

from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c
from services import calculations as calc
from services.participant_helpers import (
    loc_certified_and_valid, recompute_enrolled_count,
)

bp = Blueprint("participants", __name__)


def participant_view(p):
    return dict(p)


@bp.post("/pace/participants")
@require_roles("IntakeCoordinator")
def create_participant():
    body = c.get_body()
    program_id = c.as_str(body, "program_id")
    full_name = c.as_str(body, "full_name")
    dob = c.parse_datetime(body, "date_of_birth")
    dual_eligible = c.as_bool(body, "dual_eligible")
    # FK existence (PRD §2.5)
    c.find_or_404(db.programs, program_id)

    p = c.base_fields()
    p.update({
        "program_id": program_id,
        "full_name": full_name,
        "date_of_birth": c.iso_out(dob),
        "dual_eligible": dual_eligible,
        "enrollment_effective_date": None,
        "status": "APPLICANT",
        "active_loc_assessment_id": None,
        "active_care_plan_id": None,
        "active_enrollment_id": None,
        "ledger_billed_cents": 0,
        "ledger_reconciled_cents": 0,
        "lifetime_attendance_days": 0,
    })
    db.participants[p["id"]] = p
    return success(participant_view(p), status=201)


@bp.get("/pace/participants/<participant_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_participant(participant_id):
    p = c.find_or_404(db.participants, participant_id)
    return success(participant_view(p))


@bp.get("/pace/participants")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def list_participants():
    limit, offset = c.get_pagination()
    items = list(db.participants.values())
    for key in ("program_id", "status", "active_loc_assessment_id",
                "active_care_plan_id", "active_enrollment_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([participant_view(p) for p in page], limit, offset, total)


def _age_at(dob_dt, on_dt):
    years = on_dt.year - dob_dt.year
    if (on_dt.month, on_dt.day) < (dob_dt.month, dob_dt.day):
        years -= 1
    return years


@bp.post("/pace/participants/<participant_id>/enroll")
@require_roles("IntakeCoordinator")
def enroll(participant_id):
    p = c.find_or_404(db.participants, participant_id)
    body = c.get_body()
    eff_dt = c.parse_datetime(body, "enrollment_effective_date")
    program = db.programs.get(p["program_id"])

    # State: participant must be ELIGIBLE (priority 5, ERR_INVALID_STATE)
    if p["status"] != "ELIGIBLE":
        raise err("ERR_INVALID_STATE", "Participant not in ELIGIBLE status")

    # Program OPEN (priority 6)
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_SUSPENDED", "Program is suspended")

    # LOC certified + not expired at current clock date (priority 8)
    if not loc_certified_and_valid(p, db.clock_now()):
        raise err("ERR_LOC_NOT_CERTIFIED", "No certified, non-expired level of care")

    # Active care plan present (priority 10)
    if not p.get("active_care_plan_id"):
        raise err("ERR_NO_ACTIVE_CARE_PLAN", "No active care plan")

    # Age >= 55 at enrollment_effective_date (priority 18)
    dob_dt = c.parse_iso(p["date_of_birth"])
    if _age_at(dob_dt, eff_dt) < 55:
        raise err("ERR_AGE_INELIGIBLE", "Participant under 55 at effective date")

    # First-of-month (priority 17)
    if eff_dt.day != 1:
        raise err("ERR_NOT_FIRST_OF_MONTH", "Effective date must be first of month")

    # Roster cap (priority 23): enrolled_count < max_roster
    recompute_enrolled_count(program)
    if program["enrolled_count"] >= program["max_roster"]:
        raise err("ERR_CAPACITY_EXCEEDED", "Roster capacity exceeded")

    # Create enrollment
    enr = c.base_fields()
    lock_in_end = calc.add_days(eff_dt, program["lock_in_days"])
    enr.update({
        "participant_id": p["id"],
        "enrollment_effective_date": c.iso_out(eff_dt),
        "lock_in_end_date": c.iso_out(lock_in_end),
        "disenrollment_effective_date": None,
        "status": "OPEN",
    })
    db.enrollments[enr["id"]] = enr

    p["active_enrollment_id"] = enr["id"]
    p["enrollment_effective_date"] = c.iso_out(eff_dt)
    p["status"] = "ENROLLED"
    c.touch(p)
    recompute_enrolled_count(program)
    c.touch(program)
    return success(participant_view(p))


@bp.get("/pace/participants/<participant_id>/attendance-summary")
@require_roles("ProgramAdmin", "BillingSpecialist", "IntakeCoordinator")
def attendance_summary(participant_id):
    p = c.find_or_404(db.participants, participant_id)
    sm_str = request.args.get("service_month")
    if sm_str is None:
        raise err("ERR_INVALID_REQUEST", "Missing service_month")
    sm_dt = c.parse_iso(sm_str, "service_month")
    year, month = sm_dt.year, sm_dt.month

    completed_days = 0
    total = 0
    for d in db.attendance_days.values():
        if d["participant_id"] != p["id"]:
            continue
        if d["status"] != "COMPLETED":
            continue
        svc = c.parse_iso(d["service_date"])
        if svc.year != year or svc.month != month:
            continue
        completed_days += 1
        total += calc.ancillary_day_charge(d["meals_provided"], d["activities_count"])

    return success({
        "service_month": c.iso_out(sm_dt),
        "completed_days": completed_days,
        "month_ancillary_cents": total,
    })
