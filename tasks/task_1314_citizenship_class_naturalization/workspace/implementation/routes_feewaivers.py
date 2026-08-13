"""Fee waiver requests."""
from flask import Blueprint, g, request

from auth import authenticate, require_roles
from db import db, Rec, stamp_new, bump
from errors import err_not_found, err_forbidden, err_invalid_state, conflict
from services import (ser_fee_waiver, eligible_active_screening,
                      fee_waiver_tier, required_document_count)
from util import json_body, success_obj, paginate, v_int, v_bool, v_enum

bp = Blueprint("feewaivers", __name__)


def _get_waiver(request_id):
    r = db.fee_waivers.get(request_id)
    if r is None:
        raise err_not_found("Fee waiver request not found")
    return r


def _check_ownership(r):
    if g.user_role == "Applicant" and r.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only touch their own fee waiver requests")


@bp.post("/naturalization/applicants/<applicant_id>/fee-waiver-requests")
def create_waiver(applicant_id):
    body = json_body()
    household_size = v_int(body, "household_size", minv=1, maxv=12)
    income = v_int(body, "self_reported_income_cents", minv=0)
    benefit = v_bool(body, "self_reported_benefit")
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err_not_found("Applicant not found")
    if g.user_role == "Applicant" and applicant_id != g.user_id:
        raise err_forbidden("Applicants may only file for themselves")
    eligible_active_screening(applicant)
    for r in db.fee_waivers.values():
        if r.applicant_id == applicant.id and r.status in ("DRAFT", "SUBMITTED"):
            raise conflict("ERR_FEE_WAIVER_ALREADY_ACTIVE",
                           "Applicant already has a non-terminal fee waiver request")
    r = Rec(applicant_id=applicant.id, household_size=household_size,
            self_reported_income_cents=income, self_reported_benefit=benefit,
            provisional_tier=fee_waiver_tier(household_size, income, benefit),
            attached_document_count=0,
            required_document_count=required_document_count(household_size, benefit),
            status="DRAFT", documented_income_cents=None, documented_benefit=None,
            final_tier=None, decided_by=None)
    stamp_new(r)
    db.fee_waivers[r.id] = r
    return success_obj(ser_fee_waiver(r), 201)


@bp.get("/naturalization/fee-waiver-requests")
def list_waivers():
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    recs = list(db.fee_waivers.values())
    if g.user_role == "Applicant":
        recs = [r for r in recs if r.applicant_id == g.user_id]
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        recs = [r for r in recs if r.applicant_id == applicant_id]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r.status == status]
    return paginate(recs, ser_fee_waiver)


@bp.get("/naturalization/fee-waiver-requests/<request_id>")
def get_waiver(request_id):
    authenticate()
    require_roles("ProgramAdmin", "IntakeCoordinator", "Applicant")
    r = _get_waiver(request_id)
    _check_ownership(r)
    return success_obj(ser_fee_waiver(r))


@bp.post("/naturalization/fee-waiver-requests/<request_id>/submit")
def submit_waiver(request_id):
    body = json_body()
    attached = v_int(body, "attached_document_count", minv=0)
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    r = _get_waiver(request_id)
    _check_ownership(r)
    if r.status != "DRAFT":
        raise err_invalid_state("Only a DRAFT request may be submitted")
    if attached < r.required_document_count:
        raise conflict("ERR_FEE_WAIVER_DOCS_INSUFFICIENT",
                       "Attached document count is below the required count")
    r.attached_document_count = attached
    r.status = "SUBMITTED"
    bump(r)
    return success_obj(ser_fee_waiver(r))


@bp.post("/naturalization/fee-waiver-requests/<request_id>/decide")
def decide_waiver(request_id):
    body = json_body()
    decision = v_enum(body, "decision", ("APPROVED", "DENIED"))
    doc_income = v_int(body, "documented_income_cents", minv=0)
    doc_benefit = v_bool(body, "documented_benefit")
    authenticate()
    require_roles("ProgramAdmin")
    r = _get_waiver(request_id)
    if r.status != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED request may be decided")
    verified = fee_waiver_tier(r.household_size, doc_income, doc_benefit)
    if decision == "APPROVED" and verified == "DENIED":
        raise conflict("ERR_TIER_INELIGIBLE",
                       "Verified tier computes to DENIED; cannot approve")
    r.documented_income_cents = doc_income
    r.documented_benefit = doc_benefit
    r.decided_by = g.user_id
    if decision == "APPROVED":
        r.final_tier = verified
        r.status = "APPROVED"
    else:
        r.final_tier = None
        r.status = "DENIED"
    bump(r)
    return success_obj(ser_fee_waiver(r))


@bp.post("/naturalization/fee-waiver-requests/<request_id>/resubmit")
def resubmit_waiver(request_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator", "Applicant")
    r = _get_waiver(request_id)
    _check_ownership(r)
    if r.status != "DENIED":
        raise err_invalid_state("Only a DENIED request may be resubmitted")
    r.status = "DRAFT"
    r.attached_document_count = 0
    r.documented_income_cents = None
    r.documented_benefit = None
    r.provisional_tier = fee_waiver_tier(r.household_size,
                                         r.self_reported_income_cents,
                                         r.self_reported_benefit)
    bump(r)
    return success_obj(ser_fee_waiver(r))
