"""Payment endpoints: create (against a loan), get."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_forbidden_for_role,
    err_invalid_request,
    err_loan_not_payable,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    enforce_borrower_role_resolves,
    get_json,
    get_loan,
    get_payment,
    get_platform,
)
from services.engine import (
    post_payment_and_run_waterfall,
    stamp_create,
)
from services.serializers import serialize_payment
from utils import is_pos_int

bp = Blueprint("payments", __name__)


@bp.post("/platforms/<platform_id>/loans/<loan_id>/payments")
@require_auth(["Borrower", "PlatformOperator"])
def post_payment(platform_id, loan_id):
    platform = get_platform(platform_id)
    loan = get_loan(platform_id, loan_id)
    if g.role == "Borrower":
        enforce_borrower_role_resolves(platform_id, loan["borrower_id"])

    body = get_json()
    amount = body.get("amount_cents")
    # PRD §2.9 validation priority: state-transition legality precedes
    # the domain-specific referential and constraint rules. PRD §3.5
    # explicitly names ERR_LOAN_NOT_PAYABLE for payments against
    # CHARGED_OFF / PAID_OFF loans, so the loan-status gate fires
    # before any amount-shape validation.
    if loan["status"] not in ("ACTIVE", "DELINQUENT", "DEFAULT"):
        raise err_loan_not_payable(
            f"Loan in {loan['status']} cannot accept payments."
        )
    if not is_pos_int(amount):
        raise err_invalid_request("amount_cents must be a positive integer.")

    with store.lock:
        allocation = post_payment_and_run_waterfall(platform, loan, amount)
        payment = {
            "loan_id": loan_id,
            "borrower_id": loan["borrower_id"],
            "amount_cents": amount,
            "received_on_day_index": platform["clock_day_index"],
            "allocation": allocation,
            "status": "POSTED",
        }
        stamp_create(payment)
        store.payments[payment["id"]] = payment
    return success(serialize_payment(payment), 201)


@bp.get("/platforms/<platform_id>/payments/<payment_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def get_payment_route(platform_id, payment_id):
    p = get_payment(platform_id, payment_id)
    loan = store.loans.get(p["loan_id"])
    if loan is None:
        raise err_forbidden_for_role("Loan no longer exists.")
    if g.role == "Borrower" and g.user_id != loan["borrower_id"]:
        raise err_forbidden_for_role("Borrower may only read payments on their own loans.")
    if g.role == "Investor":
        inv_match = any(
            inv["investor_id"] == g.user_id and inv["status"] in ("CONVERTED", "LOST")
            for inv in store.investments_for_listing(loan["listing_id"])
        )
        if not inv_match:
            raise err_forbidden_for_role("Investor has no investment in this loan.")
    return success(serialize_payment(p))
