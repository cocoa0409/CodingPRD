"""Loan routes: originate, get, list."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from errors import ApiError, err_forbidden, err_resource_not_found
from middleware import require_auth
from response import list_success, success
from services.calculations import monthly_pi_payment
from services.serializers import loan_view
from utils import add_months, new_uuid, parse_iso

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("loans", __name__)


def _validate_loan_input(body):
    """Validate loan creation inputs.  Returns parsed values."""
    borrower_id = body.get("borrower_id")
    if not isinstance(borrower_id, str) or not borrower_id:
        raise ApiError("ERR_INVALID_STATE", 409, "borrower_id required")
    b = store.borrowers.get(borrower_id)
    if b is None:
        raise err_resource_not_found("Borrower not found.")

    try:
        origination_date = parse_iso(body["origination_date"])
    except Exception:
        raise ApiError("ERR_INVALID_STATE", 409, "Invalid origination_date")

    original_principal = get_int(body, "original_principal_cents")
    if original_principal is None or original_principal < 100000:
        raise ApiError("ERR_INVALID_STATE", 409, "original_principal_cents must be >= 100000")

    original_appraised = get_int(body, "original_appraised_value_cents")
    if original_appraised is None or original_appraised <= 0:
        raise ApiError("ERR_INVALID_STATE", 409, "original_appraised_value_cents must be > 0")

    interest_rate_bps = get_int(body, "interest_rate_bps")
    if interest_rate_bps is None or interest_rate_bps < 1 or interest_rate_bps > 5000:
        raise ApiError("ERR_INVALID_STATE", 409, "interest_rate_bps must be in [1, 5000]")

    term_months = get_int(body, "term_months")
    if term_months is None or term_months < 60 or term_months > 480:
        raise ApiError("ERR_INVALID_STATE", 409, "term_months must be in [60, 480]")

    pmi_monthly = get_int(body, "pmi_monthly_cents", 0) or 0
    if pmi_monthly < 0:
        raise ApiError("ERR_INVALID_STATE", 409, "pmi_monthly_cents must be >= 0")
    monthly_escrow = get_int(body, "monthly_escrow_payment_cents", 0) or 0
    if monthly_escrow < 0:
        raise ApiError("ERR_INVALID_STATE", 409, "monthly_escrow_payment_cents must be >= 0")

    return {
        "borrower_id": borrower_id,
        "origination_date": origination_date,
        "original_principal_cents": original_principal,
        "original_appraised_value_cents": original_appraised,
        "interest_rate_bps": interest_rate_bps,
        "term_months": term_months,
        "pmi_monthly_cents": pmi_monthly,
        "monthly_escrow_payment_cents": monthly_escrow,
    }


@bp.post("/loans")
@require_auth(["Servicer", "PlatformAdmin"])
def originate_loan():
    body = get_json()
    parsed = _validate_loan_input(body)
    now = store.now()
    loan_id = new_uuid()
    scheduled = monthly_pi_payment(
        parsed["original_principal_cents"],
        parsed["interest_rate_bps"],
        parsed["term_months"],
    )
    pmi_status = "ACTIVE" if parsed["pmi_monthly_cents"] > 0 else "REMOVED"
    loan = {
        "id": loan_id,
        "borrower_id": parsed["borrower_id"],
        "origination_date": parsed["origination_date"],
        "original_principal_cents": parsed["original_principal_cents"],
        "original_appraised_value_cents": parsed["original_appraised_value_cents"],
        "interest_rate_bps": parsed["interest_rate_bps"],
        "term_months": parsed["term_months"],
        "scheduled_payment_cents": scheduled,
        "principal_balance_cents": parsed["original_principal_cents"],
        "escrow_balance_cents": 0,
        "monthly_escrow_payment_cents": parsed["monthly_escrow_payment_cents"],
        "pmi_monthly_cents": parsed["pmi_monthly_cents"],
        "pmi_status": pmi_status,
        "next_due_date": add_months(parsed["origination_date"], 1),
        "posture": "CURRENT",
        "delinquency_days": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.loans[loan_id] = loan
    return success(loan_view(loan), 201)


@bp.get("/loans/<lid>")
@require_auth([
    "Servicer",
    "PlatformAdmin",
    "Borrower",
    "LossMitigationUnderwriter",
    "PmiUnderwriter",
    "ForeclosureAttorney",
])
def get_loan(lid):
    loan = get_loan_or_404(lid)
    enforce_borrower_owns_loan(loan)
    return success(loan_view(loan), 200)


@bp.get("/loans")
@require_auth(["Servicer", "PlatformAdmin"])
def list_loans():
    limit, offset = parse_pagination()
    items = list(store.loans.values())
    posture = request.args.get("posture")
    pmi_status = request.args.get("pmi_status")
    borrower_id = request.args.get("borrower_id")
    if posture:
        items = [l for l in items if l["posture"] == posture]
    if pmi_status:
        items = [l for l in items if l["pmi_status"] == pmi_status]
    if borrower_id:
        items = [l for l in items if l["borrower_id"] == borrower_id]
    items = sort_by_created_at(items)
    page = paginate(items, limit, offset)
    return list_success([loan_view(l) for l in page], limit, offset, len(items), 200)
