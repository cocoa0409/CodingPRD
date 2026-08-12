from flask import Blueprint

from db import store, base_fields, get_or_404, sorted_all
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import loan_out, case_out
from util import validate_body

bp = Blueprint("loans", __name__)


@bp.post("/loan-accounts")
def create_loan():
    require_roles("RecoveryManager")
    body = validate_body({
        "borrower_id": ("str", True, None),
        "vin": ("str", True, None),
        "governing_state_code": ("str", True, None),
        "principal_balance_cents": ("nonneg_int", True, None),
        "apr_bps": ("nonneg_int", True, None),
        "monthly_payment_cents": ("nonneg_int", True, None),
        "missed_installments": ("nonneg_int", False, None),
        "accrued_interest_cents": ("nonneg_int", False, None),
        "late_fees_cents": ("nonneg_int", False, None),
    })
    if body["borrower_id"] not in store.borrowers:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "borrower_id does not reference an existing borrower")
    loan = base_fields()
    loan.update({
        "borrower_id": body["borrower_id"],
        "vin": body["vin"],
        "governing_state_code": body["governing_state_code"],
        "principal_balance_cents": body["principal_balance_cents"],
        "apr_bps": body["apr_bps"],
        "monthly_payment_cents": body["monthly_payment_cents"],
        "missed_installments": body.get("missed_installments", 0),
        "accrued_interest_cents": body.get("accrued_interest_cents", 0),
        "late_fees_cents": body.get("late_fees_cents", 0),
        "paid_to_date_cents": 0,
        "status": "CURRENT",
        "_seq": store.next_seq(),
    })
    store.loan_accounts[loan["id"]] = loan
    return object_response(loan_out(loan), 201)


@bp.get("/loan-accounts/<lid>")
def get_loan(lid):
    require_roles(*ALL_ROLES)
    loan = get_or_404(store.loan_accounts, lid, "LoanAccount")
    return object_response(loan_out(loan))


@bp.get("/loan-accounts/<lid>/recovery-cases")
def list_loan_cases(lid):
    require_roles(*ALL_ROLES)
    get_or_404(store.loan_accounts, lid, "LoanAccount")
    rows = [c for c in sorted_all(store.recovery_cases)
            if c["loan_account_id"] == lid]
    return list_response(rows, case_out)
