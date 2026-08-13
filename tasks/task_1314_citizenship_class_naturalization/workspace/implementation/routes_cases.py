"""USCIS cases and RFE workflow."""
from datetime import timedelta

from flask import Blueprint, g, request

from auth import authenticate, require_roles
from db import db, bump, now_dt, prog_param
from errors import err_not_found, err_forbidden, err_invalid_state, conflict
from services import ser_case
from util import json_body, success_obj, paginate, v_enum

bp = Blueprint("cases", __name__)

STAGES = ("FILED", "RECEIPTED", "BIOMETRICS_COMPLETE", "INTERVIEW_SCHEDULED",
          "INTERVIEW_PASSED", "APPROVED_PENDING_OATH", "OATH_SCHEDULED",
          "NATURALIZED", "APPLICATION_DENIED")

NEXT_STAGE = {
    "FILED": "RECEIPTED",
    "RECEIPTED": "BIOMETRICS_COMPLETE",
    "BIOMETRICS_COMPLETE": "INTERVIEW_SCHEDULED",
    "INTERVIEW_SCHEDULED": "INTERVIEW_PASSED",
    "INTERVIEW_PASSED": "APPROVED_PENDING_OATH",
}

RFE_ELIGIBLE_STAGES = ("RECEIPTED", "BIOMETRICS_COMPLETE", "INTERVIEW_SCHEDULED")


def _get_case(case_id):
    c = db.cases.get(case_id)
    if c is None:
        raise err_not_found("Case not found")
    return c


def _check_ownership(c):
    if g.user_role == "Applicant" and c.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own cases")


@bp.get("/naturalization/cases")
def list_cases():
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    recs = list(db.cases.values())
    if g.user_role == "Applicant":
        recs = [c for c in recs if c.applicant_id == g.user_id]
    for field in ("applicant_id", "oath_ceremony_id", "stage", "packet_id"):
        val = request.args.get(field)
        if val is not None:
            recs = [c for c in recs if getattr(c, field) == val]
    return paginate(recs, ser_case)


@bp.get("/naturalization/cases/<case_id>")
def get_case(case_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    c = _get_case(case_id)
    _check_ownership(c)
    return success_obj(ser_case(c))


@bp.post("/naturalization/cases/<case_id>/advance")
def advance_case(case_id):
    body = json_body()
    to_stage = v_enum(body, "to_stage", STAGES)
    authenticate()
    require_roles("ProgramAdmin")
    c = _get_case(case_id)
    expected = NEXT_STAGE.get(c.stage)
    ok = (to_stage == expected) or \
        (c.stage == "INTERVIEW_PASSED" and to_stage == "APPLICATION_DENIED")
    if not ok:
        raise conflict("ERR_INVALID_STAGE_JUMP",
                       "to_stage is not the immediate next stage")
    if c.rfe_status != "NONE":
        raise conflict("ERR_RFE_OPEN",
                       "Stage advancement is blocked while an RFE is open")
    c.stage = to_stage
    bump(c)
    return success_obj(ser_case(c))


@bp.post("/naturalization/cases/<case_id>/issue-rfe")
def issue_rfe(case_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    c = _get_case(case_id)
    if c.stage not in RFE_ELIGIBLE_STAGES or c.rfe_status != "NONE":
        raise err_invalid_state("Case state does not permit issuing an RFE")
    c.rfe_status = "ISSUED"
    c.rfe_issued_at = now_dt()
    c.rfe_deadline = now_dt() + timedelta(days=prog_param("rfe_deadline_days"))
    bump(c)
    return success_obj(ser_case(c))


@bp.post("/naturalization/cases/<case_id>/respond-rfe")
def respond_rfe(case_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "ProgramAdmin")
    c = _get_case(case_id)
    if c.rfe_status not in ("ISSUED", "OVERDUE"):
        raise err_invalid_state("No open RFE to respond to")
    c.rfe_status = "RESPONDED"
    bump(c)
    return success_obj(ser_case(c))


@bp.post("/naturalization/cases/<case_id>/clear-rfe")
def clear_rfe(case_id):
    json_body()
    authenticate()
    require_roles("ProgramAdmin")
    c = _get_case(case_id)
    if c.rfe_status != "RESPONDED":
        raise err_invalid_state("Only a RESPONDED RFE may be cleared")
    c.rfe_status = "NONE"
    c.rfe_issued_at = None
    c.rfe_deadline = None
    bump(c)
    return success_obj(ser_case(c))
