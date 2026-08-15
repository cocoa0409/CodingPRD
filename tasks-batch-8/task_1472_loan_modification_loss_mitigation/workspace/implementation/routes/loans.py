from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize, check_borrower_ownership
from errors import (
    ERR_APPLICATION_STATE_INVALID,
    ERR_BORROWER_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_STALE_LOAN_VERSION,
    raise_err,
)
from services import (
    HARDSHIP_TYPES,
    NON_TERMINAL_APP_STATES,
    ACK_SLA_DAYS,
    application_out,

    loan_out,
    withdraw_application,
)
from datetime import timedelta

import clock
from util import (
    body_json,
    get_or_404,
    list_response,
    new_record,
    opt_int,
    req_enum,
    req_int,
    req_str,
    success_object,
    bump,
)

bp = Blueprint("loans", __name__)


@bp.route("/loans", methods=["POST"])
def create_loan():
    _, role = authenticate()
    authorize(role, ["ServicingAdmin"])
    body = body_json()
    borrower_id = req_str(body, "borrower_id")
    loan_number = req_str(body, "loan_number")
    property_state_code = req_str(body, "property_state_code")
    upb = req_int(body, "unpaid_principal_balance_cents")
    rate = req_int(body, "interest_rate_bp")
    term = req_int(body, "remaining_term_months")
    arrears = opt_int(body, "arrears_cents", 0)
    escrow_balance = opt_int(body, "escrow_balance_cents", 0)
    escrow_monthly = opt_int(body, "escrow_monthly_cents", 0)
    delinquency_days = opt_int(body, "delinquency_days", 0)

    get_or_404(store.borrowers, borrower_id, ERR_BORROWER_NOT_FOUND, "Borrower")

    rec = new_record()
    rec.update({
        "borrower_id": borrower_id,
        "loan_number": loan_number,
        "property_state_code": property_state_code,
        "unpaid_principal_balance_cents": upb,
        "interest_rate_bp": rate,
        "remaining_term_months": term,
        "arrears_cents": arrears,
        "suspense_cents": 0,
        "deferred_principal_cents": 0,
        "escrow_balance_cents": escrow_balance,
        "escrow_monthly_cents": escrow_monthly,
        "delinquency_days": delinquency_days,
        "workout_status": "DELINQUENT" if delinquency_days > 0 else "PERFORMING",
    })
    store.loans[rec["id"]] = rec
    return success_object(loan_out(rec), 201)


@bp.route("/loans/<rid>", methods=["GET"])
def get_loan(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    return success_object(loan_out(rec))


@bp.route("/loans", methods=["GET"])
def list_loans():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.loans.values())
    borrower_id = request.args.get("borrower_id")
    workout_status = request.args.get("workout_status")
    if borrower_id is not None:
        records = [r for r in records if r["borrower_id"] == borrower_id]
    if workout_status is not None:
        records = [r for r in records if r["workout_status"] == workout_status]
    return list_response(records, loan_out)


@bp.route("/loans/<rid>/applications", methods=["POST"])
def create_application(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    body = body_json()
    expected_loan_version = req_int(body, "expected_loan_version")
    hardship_type = req_enum(body, "hardship_type", HARDSHIP_TYPES)
    stated_income = req_int(body, "stated_monthly_income_cents")

    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    check_borrower_ownership(uid, loan)

    # OCC (priority 6)
    if expected_loan_version != loan["version"]:
        raise_err(ERR_STALE_LOAN_VERSION, "Loan version has advanced")

    # state (priority 7): supersession blocked from TRIAL_ACTIVE / TRIAL_PASSED
    existing = [a for a in store.applications.values()
                if a["loan_id"] == loan["id"] and a["status"] in NON_TERMINAL_APP_STATES]
    for a in existing:
        if a["status"] in ("TRIAL_ACTIVE", "TRIAL_PASSED"):
            raise_err(ERR_APPLICATION_STATE_INVALID,
                      "Existing application is in %s and cannot be superseded" % a["status"])

    created = clock.now()
    app_rec = new_record()
    app_rec.update({
        "loan_id": loan["id"],
        "hardship_type": hardship_type,
        "stated_monthly_income_cents": stated_income,
        "status": "SUBMITTED",
        "verified_monthly_income_cents": 0,
        "outstanding_doc_categories": ["INCOME_PROOF", "HARDSHIP_AFFIDAVIT", "BANK_STATEMENT"],
        "completed_at": None,
        "acknowledgement_due_at": created + timedelta(days=ACK_SLA_DAYS),
        "acknowledged_at": None,
        "evaluation_deadline": None,
        "active_evaluation_id": None,
        "superseded_by_application_id": None,
    })
    store.applications[app_rec["id"]] = app_rec

    # implicit supersession: prior non-terminal applications auto-WITHDRAW
    for a in existing:
        withdraw_application(a, superseded_by_id=app_rec["id"])

    if loan["workout_status"] == "DELINQUENT":
        loan["workout_status"] = "LOSS_MIT_REVIEW"
    bump(loan)
    return success_object(application_out(app_rec), 201)


@bp.route("/loans/<rid>/applications", methods=["GET"])
def list_loan_applications(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    loan = get_or_404(store.loans, rid, ERR_LOAN_NOT_FOUND, "Loan")
    records = [a for a in store.applications.values() if a["loan_id"] == loan["id"]]
    return list_response(records, application_out)
