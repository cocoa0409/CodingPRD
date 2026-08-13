"""Applicants, screenings, readiness."""
from datetime import timedelta

from flask import Blueprint, g, request

from auth import authenticate, require_roles
from db import db, Rec, stamp_new, bump, now_dt
from errors import err_not_found, err_forbidden, err_invalid_request, err_stale_version
from services import (ser_applicant, ser_screening, screening_outcome, readiness)
from util import (json_body, success_obj, paginate, v_str, v_int, v_bool,
                  v_date)

bp = Blueprint("applicants", __name__)


def _get_applicant(applicant_id):
    a = db.applicants.get(applicant_id)
    if a is None:
        raise err_not_found("Applicant not found")
    return a


def _check_applicant_ownership(applicant):
    if g.user_role == "Applicant" and applicant.id != g.user_id:
        raise err_forbidden("Applicants may only access their own record")


@bp.post("/naturalization/applicants")
def create_applicant():
    body = json_body()
    full_name = v_str(body, "full_name")
    email = v_str(body, "email")
    dob = v_date(body, "date_of_birth")
    lang = v_str(body, "preferred_language", required=False) or "en"
    authenticate()
    require_roles("IntakeCoordinator")
    a = Rec(full_name=full_name, email=email, date_of_birth=dob,
            preferred_language=lang, stage="REGISTERED",
            current_screening_id=None, voter_registration_referred=False)
    stamp_new(a)
    db.applicants[a.id] = a
    return success_obj(ser_applicant(a), 201)


@bp.get("/naturalization/applicants")
def list_applicants():
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator")
    recs = list(db.applicants.values())
    csid = request.args.get("current_screening_id")
    if csid is not None:
        recs = [a for a in recs if a.current_screening_id == csid]
    stage = request.args.get("stage")
    if stage is not None:
        recs = [a for a in recs if a.stage == stage]
    return paginate(recs, ser_applicant)


@bp.get("/naturalization/applicants/<applicant_id>")
def get_applicant(applicant_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    a = _get_applicant(applicant_id)
    _check_applicant_ownership(a)
    return success_obj(ser_applicant(a))


@bp.post("/naturalization/applicants/<applicant_id>/screenings")
def create_screening(applicant_id):
    body = json_body()
    expected_version = v_int(body, "expected_applicant_version")
    marital = v_bool(body, "marital_to_citizen")
    lpr_months = v_int(body, "lpr_months", minv=0)
    crm = v_int(body, "continuous_residence_months", minv=0)
    ppd = v_int(body, "physical_presence_days", minv=0)
    age = v_int(body, "age_years", minv=0)
    english = v_int(body, "english_level", minv=0, maxv=4)
    civics = v_int(body, "civics_practice_pct", minv=0, maxv=100)
    legal_flag = v_bool(body, "has_legal_flag")
    authenticate()
    require_roles("IntakeCoordinator")
    a = _get_applicant(applicant_id)

    outcome = screening_outcome(marital, lpr_months, crm, ppd, age, english,
                                civics, legal_flag)
    # OCC: final guard before commit
    if expected_version != a.version:
        raise err_stale_version()

    s = Rec(applicant_id=a.id, marital_to_citizen=marital, lpr_months=lpr_months,
            continuous_residence_months=crm, physical_presence_days=ppd,
            age_years=age, english_level=english, civics_practice_pct=civics,
            has_legal_flag=legal_flag, outcome=outcome, status="ACTIVE",
            expires_at=now_dt() + timedelta(days=180))
    stamp_new(s)
    db.screenings[s.id] = s

    prior = None
    if a.current_screening_id:
        prior = db.screenings.get(a.current_screening_id)
    if prior is not None and prior.status == "ACTIVE":
        prior.status = "SUPERSEDED"
        bump(prior)
    a.current_screening_id = s.id
    if outcome in ("ELIGIBLE", "ELIGIBLE_WITH_EXEMPTION") and a.stage == "REGISTERED":
        a.stage = "SCREENED"
    bump(a)
    return success_obj(ser_screening(s), 201)


@bp.get("/naturalization/applicants/<applicant_id>/screenings")
def list_screenings(applicant_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    a = _get_applicant(applicant_id)
    _check_applicant_ownership(a)
    recs = [s for s in db.screenings.values() if s.applicant_id == a.id]
    return paginate(recs, ser_screening)


@bp.get("/naturalization/applicants/<applicant_id>/readiness")
def get_readiness(applicant_id):
    variant = request.args.get("variant", "attained")
    if variant not in ("attained", "projected"):
        raise err_invalid_request("variant must be attained or projected")
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    a = _get_applicant(applicant_id)
    _check_applicant_ownership(a)
    return success_obj(readiness(a, variant))
