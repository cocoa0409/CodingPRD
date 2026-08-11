"""Redemption / reinstatement quotes (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all, now
from errors import (
    ApiError, ERR_INVALID_CASE_STATE, ERR_INVALID_QUOTE_STATE,
    ERR_FORBIDDEN_OWNERSHIP, ERR_STALE_VERSION, ERR_QUOTE_EXPIRED,
    ERR_PAYMENT_INSUFFICIENT,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import quote_out
from services import calc
from services.transitions import record_payment
from util import validate_body

bp = Blueprint("quotes", __name__)

QUOTE_TYPES = {"REDEMPTION", "REINSTATEMENT"}


@bp.post("/recovery-cases/<cid>/redemption-quotes")
def create_quote(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    body = validate_body({
        "quote_type": ("str", True, QUOTE_TYPES),
        "expected_recovery_case_version": ("int", True, None),
    })
    if case["status"] not in ("COLLATERAL_SECURED", "REDEMPTION_OPEN"):
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit a redemption quote")
    if body["expected_recovery_case_version"] != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_recovery_case_version does not match the case version")
    loan = store.loan_accounts[case["loan_account_id"]]
    issued_at = store.clock
    if case["status"] == "COLLATERAL_SECURED":
        # First quote fixes the redemption deadline; later quotes never extend it.
        case["redemption_deadline"] = issued_at + timedelta(
            days=calc.REDEMPTION_PERIOD_DAYS)
    valid_until = case["redemption_deadline"]
    amount, per_diem = calc.quote_amount(case, loan, body["quote_type"], valid_until)
    prior = store.redemption_quotes.get(
        case.get("current_redemption_quote_id") or "")
    quote = base_fields()
    quote.update({
        "recovery_case_id": case["id"],
        "quote_type": body["quote_type"],
        "status": "ISSUED",
        "issued_at": issued_at,
        "valid_until": valid_until,
        "quoted_amount_cents": amount,
        "per_diem_cents": per_diem,
        "superseded_by_id": None,
        "_seq": store.next_seq(),
    })
    store.redemption_quotes[quote["id"]] = quote
    if prior is not None and prior["status"] == "ISSUED":
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = quote["id"]
        touch(prior)
    case["status"] = "REDEMPTION_OPEN"
    case["current_redemption_quote_id"] = quote["id"]
    touch(case)
    return object_response(quote_out(quote), 201)


@bp.get("/recovery-cases/<cid>/redemption-quotes")
def list_quotes(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [q for q in sorted_all(store.redemption_quotes)
            if q["recovery_case_id"] == cid]
    return list_response(rows, quote_out)


@bp.post("/redemption-quotes/<qid>/accept")
def accept_quote(qid):
    user_id, _role = require_roles("Borrower")
    quote = get_or_404(store.redemption_quotes, qid, "RedemptionQuote")
    case = store.recovery_cases[quote["recovery_case_id"]]
    loan = store.loan_accounts[case["loan_account_id"]]
    if loan["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")
    body = validate_body({
        "payment_amount_cents": ("pos_int", True, None),
    })
    # state tier tie-break: the quote's own state before cross-entity checks.
    if quote["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_QUOTE_STATE, 409,
                       f"Quote status {quote['status']} does not permit accept")
    if case["status"] != "REDEMPTION_OPEN":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit quote accept")
    if now() > quote["valid_until"]:
        raise ApiError(ERR_QUOTE_EXPIRED, 422, "Quote validity window has passed")
    if body["payment_amount_cents"] < quote["quoted_amount_cents"]:
        raise ApiError(ERR_PAYMENT_INSUFFICIENT, 422,
                       "Payment amount is below the quoted amount")
    quote["status"] = "ACCEPTED"
    touch(quote)
    if quote["quote_type"] == "REDEMPTION":
        case["status"] = "REDEEMED"
        loan["status"] = "REDEEMED_PAID"
    else:
        case["status"] = "REINSTATED"
        loan["status"] = "CURRENT"
    touch(case)
    # record_payment touches the loan once, covering both field mutations.
    record_payment(case, loan, body["payment_amount_cents"])
    return object_response(quote_out(quote))
