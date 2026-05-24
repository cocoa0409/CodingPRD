"""Payment endpoints."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_BORROWER_DISCHARGED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PAYMENT_DATE_OUT_OF_WINDOW,
    ERR_PAYMENT_EXCEEDS_BALANCE,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import calc, loan_ops, serializer

bp = Blueprint("payments", __name__)


POSTABLE_LOAN_STATES = {"GRACE", "REPAYMENT", "DEFERMENT", "FORBEARANCE", "DELINQUENT", "DEFAULT"}
VALID_SOURCES = {"ACH", "CHECK", "PAYROLL_DEDUCT", "EMPLOYER_BENEFIT", "TREASURY_OFFSET"}


def _parse_iso_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


@bp.post("/v1/payments")
@require_roles({"LoanServicer"})
def create_payment():
    body = parse_json_body()
    loan_id = get_field(body, "loan_id")
    amount_cents = get_field(body, "amount_cents")
    posted_on = get_field(body, "posted_on")
    source = get_field(body, "source")

    # Existence (priority 20)
    loan = must_get(db.loans, loan_id, "Loan")

    # Basic body validation
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < 1:
        raise APIError(ERR_INVALID_REQUEST, "amount_cents must be int >= 1")
    if source not in VALID_SOURCES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid source")
    if not isinstance(posted_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted_on):
        raise APIError(ERR_INVALID_REQUEST, "posted_on must be YYYY-MM-DD")

    # Priority 21: state precondition
    if loan["status"] not in POSTABLE_LOAN_STATES:
        raise APIError(ERR_INVALID_STATE, "Loan not in postable state")

    # Priority 22: cross-entity — borrower not fully discharged/paid-off
    borrower_loans = [l for l in db.loans.values() if l["borrower_id"] == loan["borrower_id"]]
    if borrower_loans and all(l["status"] in {"DISCHARGED", "PAID_OFF"} for l in borrower_loans):
        raise APIError(ERR_BORROWER_DISCHARGED, "Borrower has no active loans")

    # Priority 26: posted_on window
    clock = _parse_iso_date(db.get_clock_date())
    p_date = _parse_iso_date(posted_on)
    if p_date > clock or p_date < (clock - timedelta(days=15)):
        raise APIError(ERR_PAYMENT_DATE_OUT_OF_WINDOW, "posted_on outside [clock - 15d, clock]")

    # Priority 27: amount does not exceed balance
    # Compute via waterfall — fees first
    applied_fees, applied_interest, applied_principal, remaining = calc.payment_allocation(
        amount_cents,
        loan["status"],
        source,
        loan["accrued_interest_cents"],
        loan["outstanding_principal_cents"],
    )
    if remaining > 0:
        raise APIError(ERR_PAYMENT_EXCEEDS_BALANCE, "Payment exceeds loan balance")

    # Apply
    loan["accrued_interest_cents"] -= applied_interest
    loan["outstanding_principal_cents"] -= applied_principal

    pid = db.new_id()
    now = db.now_iso()
    payment = {
        "id": pid,
        "loan_id": loan_id,
        "amount_cents": amount_cents,
        "posted_on": posted_on,
        "source": source,
        "applied_to_interest_cents": applied_interest,
        "applied_to_principal_cents": applied_principal,
        "applied_to_fees_cents": applied_fees,
        "status": "POSTED",
        "recorded_by_user_id": current_user_id(),
        "pslf_qualifying": False,  # recount will set
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.payments[pid] = payment

    # Cascade: if loan fully paid (principal and interest zero), → PAID_OFF
    if loan["outstanding_principal_cents"] == 0 and loan["accrued_interest_cents"] == 0:
        loan_ops.transition_to_paid_off(loan, posted_on, current_user_id())
    elif loan["status"] == "DELINQUENT":
        # If payment cures full arrears, cascade DELINQUENT → REPAYMENT
        if loan_ops.payment_cures_arrears(loan, amount_cents):
            loan_ops.transition_delinquent_to_repayment(loan, posted_on, current_user_id())
        else:
            # Still delinquent; bump version for the payment-driven mutation
            serializer.bump_loan(loan)
            serializer.recompute_borrower(loan["borrower_id"])
    else:
        # Generic case — bump loan version for the payment-driven mutation
        serializer.bump_loan(loan)
        serializer.recompute_borrower(loan["borrower_id"])

    # Trigger PSLF tracker recount for this borrower
    loan_ops.maybe_recount_for_borrower(loan["borrower_id"])

    return success(serializer.serialize_payment(payment), status=201)


@bp.get("/v1/payments/<payment_id>")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def get_payment(payment_id):
    p = must_get(db.payments, payment_id, "Payment")
    if current_role() == "Borrower":
        loan = db.loans.get(p["loan_id"])
        if not loan or loan["borrower_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this payment")
    return success(serializer.serialize_payment(p), status=200)


@bp.get("/v1/payments")
@require_roles({"LoanServicer", "PSLFAdjudicator", "Borrower"})
def list_payments():
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")
    status_filter = request.args.get("status")
    items = list(db.payments.values())
    if current_role() == "Borrower":
        own_loan_ids = {l["id"] for l in db.loans.values() if l["borrower_id"] == current_user_id()}
        items = [p for p in items if p["loan_id"] in own_loan_ids]
    if loan_filter:
        items = [p for p in items if p["loan_id"] == loan_filter]
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_payment(p) for p in page], limit, offset, total)


@bp.post("/v1/payments/<payment_id>/reverse")
@require_roles({"LoanServicer"})
def reverse_payment(payment_id):
    payment = must_get(db.payments, payment_id, "Payment")
    if payment["status"] != "POSTED":
        raise APIError(ERR_INVALID_STATE, "Payment not POSTED")
    # Must be within 30 days
    clock = _parse_iso_date(db.get_clock_date())
    p_date = _parse_iso_date(payment["posted_on"])
    if p_date < (clock - timedelta(days=30)):
        raise APIError(ERR_INVALID_STATE, "Payment too old to reverse")
    loan = db.loans.get(payment["loan_id"])
    if loan is None:
        raise APIError(ERR_NOT_FOUND, "Loan not found")

    # Reverse: status → REVERSED; un-apply balances
    payment["status"] = "REVERSED"
    payment["pslf_qualifying"] = False
    loan["outstanding_principal_cents"] += payment["applied_to_principal_cents"]
    loan["accrued_interest_cents"] += payment["applied_to_interest_cents"]
    serializer.bump_payment(payment)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])

    # PSLF recount may flip ELIGIBLE_FOR_FORGIVENESS → TRACKING
    loan_ops.maybe_recount_for_borrower(loan["borrower_id"])

    return success(serializer.serialize_payment(payment), status=200)
