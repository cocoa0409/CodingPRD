"""Loan officers."""
from flask import Blueprint, request

import db
from errors import invalid_state
from middleware import body, get_or_404, list_page, require_field, require_roles
from response import success_list, success_obj
from services.officer import officer_components

bp = Blueprint("loan_officers", __name__)

ALL = (
    "BankAdmin", "LendingDataOps", "LoanOfficer", "FairLendingAnalyst",
    "FairLendingOfficer", "ComplianceDirector", "RemediationSpecialist",
)
ANALYTICS = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


@bp.post("/fair-lending/loan-officers")
@require_roles("BankAdmin")
def create_officer():
    data = body()
    branch_id = require_field(data, "branch_id")
    full_name = require_field(data, "full_name")
    get_or_404("branches", branch_id, "Branch")
    rec = db.new_record(
        {
            "branch_id": branch_id,
            "full_name": full_name,
            "status": "ACTIVE",
            "approved_exception_count": 0,
            "confirmed_override_count": 0,
            "validated_application_count": 0,
            "risk_score": 0,
            "monitoring_tier": "GREEN",
        }
    )
    db.STORES["officers"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/loan-officers")
@require_roles(*ALL)
def list_officers():
    page, total, limit, offset = list_page(
        "officers",
        {
            "branch_id": request.args.get("branch_id"),
            "status": request.args.get("status"),
            "monitoring_tier": request.args.get("monitoring_tier"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/loan-officers/<officerId>")
@require_roles(*ALL)
def get_officer(officerId):
    rec = get_or_404("officers", officerId, "LoanOfficer")
    return success_obj(db.public(rec))


@bp.get("/fair-lending/loan-officers/<officerId>/risk-scorecard")
@require_roles(*ANALYTICS)
def risk_scorecard(officerId):
    rec = get_or_404("officers", officerId, "LoanOfficer")
    return success_obj(officer_components(rec))


@bp.post("/fair-lending/loan-officers/<officerId>/suspend")
@require_roles("ComplianceDirector")
def suspend_officer(officerId):
    rec = get_or_404("officers", officerId, "LoanOfficer")
    if rec["status"] != "ACTIVE":
        raise invalid_state("LoanOfficer is not ACTIVE")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/loan-officers/<officerId>/reinstate")
@require_roles("ComplianceDirector")
def reinstate_officer(officerId):
    rec = get_or_404("officers", officerId, "LoanOfficer")
    if rec["status"] != "SUSPENDED":
        raise invalid_state("LoanOfficer is not SUSPENDED")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_obj(db.public(rec))
