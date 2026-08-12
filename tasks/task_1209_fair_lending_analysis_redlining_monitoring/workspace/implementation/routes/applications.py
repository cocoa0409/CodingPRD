"""Applications: intake, validate, OCC-guarded correction, exclusion."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_request, invalid_state
from middleware import (
    body, check_enum, check_int, check_number, get_or_404, list_page,
    occ_check, require_field, require_roles,
)
from response import success_list, success_obj
from services.analysis import app_frozen
from services.officer import refresh_officer

bp = Blueprint("applications", __name__)

PRODUCTS = ("CONVENTIONAL", "FHA", "VA")
GROUPS = ("PROTECTED_1", "PROTECTED_2", "CONTROL")
OUTCOMES = ("ORIGINATED", "DENIED", "WITHDRAWN", "APPROVED_NOT_ACCEPTED")

LIST_ROLES = (
    "BankAdmin", "LendingDataOps", "FairLendingAnalyst", "FairLendingOfficer",
    "ComplianceDirector",
)
GET_ROLES = LIST_ROLES + ("LoanOfficer",)


@bp.post("/fair-lending/applications")
@require_roles("LendingDataOps")
def create_application():
    data = body()
    market_id = require_field(data, "market_id")
    branch_id = require_field(data, "branch_id")
    loan_officer_id = require_field(data, "loan_officer_id")
    product_type = check_enum(require_field(data, "product_type"), PRODUCTS, "product_type")
    applicant_group = check_enum(
        require_field(data, "applicant_group"), GROUPS, "applicant_group"
    )
    outcome = check_enum(require_field(data, "outcome"), OUTCOMES, "outcome")
    note_rate_bps = check_int(require_field(data, "note_rate_bps"), "note_rate_bps")
    loan_amount_cents = check_int(
        require_field(data, "loan_amount_cents"), "loan_amount_cents"
    )
    credit_score = check_int(require_field(data, "credit_score"), "credit_score")
    if not (300 <= credit_score <= 900):
        raise invalid_request("credit_score must be between 300 and 900")
    dti_pct = check_number(require_field(data, "dti_pct"), "dti_pct")
    application_date = require_field(data, "application_date")
    decision_date = require_field(data, "decision_date")
    # Body-level foreign keys must exist (404), left to right.
    get_or_404("markets", market_id, "Market")
    get_or_404("branches", branch_id, "Branch")
    get_or_404("officers", loan_officer_id, "LoanOfficer")
    rec = db.new_record(
        {
            "market_id": market_id,
            "branch_id": branch_id,
            "loan_officer_id": loan_officer_id,
            "product_type": product_type,
            "applicant_group": applicant_group,
            "outcome": outcome,
            "note_rate_bps": note_rate_bps,
            "loan_amount_cents": loan_amount_cents,
            "credit_score": credit_score,
            "dti_pct": dti_pct,
            "application_date": application_date,
            "decision_date": decision_date,
            "status": "RECEIVED",
            "has_exception": "NONE",
        }
    )
    db.STORES["applications"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/applications")
@require_roles(*LIST_ROLES)
def list_applications():
    page, total, limit, offset = list_page(
        "applications",
        {
            "market_id": request.args.get("market_id"),
            "branch_id": request.args.get("branch_id"),
            "loan_officer_id": request.args.get("loan_officer_id"),
            "product_type": request.args.get("product_type"),
            "applicant_group": request.args.get("applicant_group"),
            "outcome": request.args.get("outcome"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/applications/<applicationId>")
@require_roles(*GET_ROLES)
def get_application(applicationId):
    rec = get_or_404("applications", applicationId, "Application")
    return success_obj(db.public(rec))


@bp.post("/fair-lending/applications/<applicationId>/validate")
@require_roles("LendingDataOps")
def validate_application(applicationId):
    rec = get_or_404("applications", applicationId, "Application")
    if rec["status"] == "EXCLUDED":
        raise already_terminal("Application is EXCLUDED")
    if rec["status"] != "RECEIVED":
        raise invalid_state("Application is not in RECEIVED status")
    rec["status"] = "VALIDATED"
    db.touch(rec)
    officer = db.STORES["officers"].get(rec["loan_officer_id"])
    if officer is not None:
        officer["validated_application_count"] += 1
        refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))


@bp.put("/fair-lending/applications/<applicationId>")
@require_roles("LendingDataOps")
def correct_application(applicationId):
    rec = get_or_404("applications", applicationId, "Application")
    data = body()
    occ_check(data, "expected_application_version", rec["version"])
    if rec["status"] == "EXCLUDED":
        raise already_terminal("Application is EXCLUDED")
    if app_frozen(rec["id"]):
        raise err(
            "ERR_APPLICATION_LOCKED",
            "Application is frozen in a FINALIZED/ARCHIVED analysis-run snapshot",
        )
    updates = {}
    if "outcome" in data and data["outcome"] is not None:
        updates["outcome"] = check_enum(data["outcome"], OUTCOMES, "outcome")
    if "note_rate_bps" in data and data["note_rate_bps"] is not None:
        updates["note_rate_bps"] = check_int(data["note_rate_bps"], "note_rate_bps")
    if "credit_score" in data and data["credit_score"] is not None:
        cs = check_int(data["credit_score"], "credit_score")
        if not (300 <= cs <= 900):
            raise invalid_request("credit_score must be between 300 and 900")
        updates["credit_score"] = cs
    if "dti_pct" in data and data["dti_pct"] is not None:
        updates["dti_pct"] = check_number(data["dti_pct"], "dti_pct")
    was_validated = rec["status"] == "VALIDATED"
    rec.update(updates)
    if was_validated:
        # Correction pulls the record back to RECEIVED; officer count drops and
        # covering DATA_LOCKED runs become stale (evaluated at compute time).
        rec["status"] = "RECEIVED"
        officer = db.STORES["officers"].get(rec["loan_officer_id"])
        if officer is not None:
            officer["validated_application_count"] -= 1
            refresh_officer(officer, force_touch=True)
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/applications/<applicationId>/exclude")
@require_roles("LendingDataOps")
def exclude_application(applicationId):
    rec = get_or_404("applications", applicationId, "Application")
    if rec["status"] == "EXCLUDED":
        raise already_terminal("Application is EXCLUDED")
    if app_frozen(rec["id"]):
        raise err(
            "ERR_APPLICATION_LOCKED",
            "Application is frozen in a FINALIZED/ARCHIVED analysis-run snapshot",
        )
    was_validated = rec["status"] == "VALIDATED"
    rec["status"] = "EXCLUDED"
    db.touch(rec)
    if was_validated:
        officer = db.STORES["officers"].get(rec["loan_officer_id"])
        if officer is not None:
            officer["validated_application_count"] -= 1
            refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))
