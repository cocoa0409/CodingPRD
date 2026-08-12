"""Recovery cases, cure notices/payments, and the recovery ledger."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, base_fields, touch, get_or_404, sorted_all
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_CASE_STATE,
    ERR_DUPLICATE_OPEN_CASE, ERR_FORBIDDEN_OWNERSHIP, ERR_STALE_VERSION,
    ERR_PAYMENT_INSUFFICIENT,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import case_out, cure_notice_out, ledger_out
from services import calc
from services.transitions import new_ledger_entry, record_payment
from util import validate_body

bp = Blueprint("cases", __name__)

CASE_STATUSES = {
    "OPENED", "CURE_PENDING", "CURED", "CURE_EXPIRED", "REPO_ACTIVE",
    "COLLATERAL_SECURED", "REDEMPTION_OPEN", "REDEEMED", "REINSTATED",
    "CONSIGNMENT_PENDING", "IN_AUCTION", "SALE_CONFIRMED",
    "DEFICIENCY_NOTICED", "COMPLAINT_REVIEW", "RESTITUTION", "CLOSED",
}


def case_loan(case):
    return store.loan_accounts[case["loan_account_id"]]


def _check_case_borrower(case, user_id):
    """Ownership scope: a Borrower acts only on cases of their own loans."""
    if case_loan(case)["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")


@bp.post("/recovery-cases")
def create_case():
    user_id, _role = require_roles("RecoveryManager")
    body = validate_body({
        "loan_account_id": ("str", True, None),
        "default_reason": ("str", True, None),
    })
    loan = store.loan_accounts.get(body["loan_account_id"])
    if loan is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "loan_account_id does not reference an existing loan")
    for c in store.recovery_cases.values():
        if c["loan_account_id"] == loan["id"] and c["status"] != "CLOSED":
            raise ApiError(ERR_DUPLICATE_OPEN_CASE, 409,
                           "A non-CLOSED RecoveryCase already exists for the loan")
    case = base_fields()
    case.update({
        "loan_account_id": loan["id"],
        "default_reason": body["default_reason"],
        "opened_by_user_id": user_id,
        "status": "OPENED",
        "cure_deadline": None,
        "redemption_deadline": None,
        "pre_complaint_state": None,
        "current_cure_notice_id": None,
        "current_redemption_quote_id": None,
        "collateral_secured_at": None,
        "odometer": None,
        "condition_grade": None,
        "trade_in_value_cents": None,
        "auction_guide_low_cents": None,
        "sold_at": None,
        "property_item_count": 0,
        "_seq": store.next_seq(),
    })
    store.recovery_cases[case["id"]] = case
    loan["status"] = "IN_DEFAULT"
    touch(loan)
    return object_response(case_out(case), 201)


@bp.get("/recovery-cases/<cid>")
def get_case(cid):
    require_roles(*ALL_ROLES)
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    return object_response(case_out(case))


@bp.get("/recovery-cases")
def list_cases():
    require_roles(*ALL_ROLES)
    status = request.args.get("status")
    loan_account_id = request.args.get("loan_account_id")
    if status is not None and status not in CASE_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter value")
    rows = sorted_all(store.recovery_cases)
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if loan_account_id is not None:
        rows = [c for c in rows if c["loan_account_id"] == loan_account_id]
    return list_response(rows, case_out)


@bp.post("/recovery-cases/<cid>/close")
def close_case(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    closable = {"CURED", "REDEEMED", "REINSTATED", "RESTITUTION"}
    if case["status"] in closable:
        pass
    elif case["status"] == "DEFICIENCY_NOTICED":
        for n in store.deficiency_notices.values():
            if (n["recovery_case_id"] == case["id"]
                    and n["status"] not in ("PAID", "WAIVED", "VOID")):
                raise ApiError(ERR_INVALID_CASE_STATE, 409,
                               "Case has deficiency notices not yet settled")
    else:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit close")
    if case["status"] == "DEFICIENCY_NOTICED":
        loan = case_loan(case)
        if loan["status"] not in ("REDEEMED_PAID", "CURRENT"):
            loan["status"] = "CHARGED_OFF"
            touch(loan)
    case["status"] = "CLOSED"
    touch(case)
    return object_response(case_out(case))


@bp.post("/recovery-cases/<cid>/cure-notices")
def create_cure_notice(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    body = validate_body({
        "expected_recovery_case_version": ("int", True, None),
    })
    if case["status"] not in ("OPENED", "CURE_PENDING"):
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit a cure notice")
    if body["expected_recovery_case_version"] != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_recovery_case_version does not match the case version")
    loan = case_loan(case)
    prior = store.cure_notices.get(case.get("current_cure_notice_id") or "")
    notice = base_fields()
    notice.update({
        "recovery_case_id": case["id"],
        "status": "SENT",
        "sent_at": store.clock,
        "cure_amount_cents": calc.cure_amount_cents(case, loan),
        "superseded_by_id": None,
        "_seq": store.next_seq(),
    })
    store.cure_notices[notice["id"]] = notice
    if prior is not None and prior["status"] == "SENT":
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = notice["id"]
        touch(prior)
    case["status"] = "CURE_PENDING"
    case["cure_deadline"] = notice["sent_at"] + timedelta(days=calc.CURE_PERIOD_DAYS)
    case["current_cure_notice_id"] = notice["id"]
    touch(case)
    return object_response(cure_notice_out(notice), 201)


@bp.get("/recovery-cases/<cid>/cure-notices")
def list_cure_notices(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [n for n in sorted_all(store.cure_notices)
            if n["recovery_case_id"] == cid]
    return list_response(rows, cure_notice_out)


@bp.post("/recovery-cases/<cid>/cure-payments")
def create_cure_payment(cid):
    user_id, _role = require_roles("Borrower")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    _check_case_borrower(case, user_id)
    body = validate_body({
        "amount_cents": ("pos_int", True, None),
    })
    if case["status"] != "CURE_PENDING":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit a cure payment")
    notice = store.cure_notices.get(case.get("current_cure_notice_id") or "")
    required = notice["cure_amount_cents"] if notice is not None else 0
    if body["amount_cents"] < required:
        raise ApiError(ERR_PAYMENT_INSUFFICIENT, 422,
                       "Payment amount is below the cure amount")
    loan = case_loan(case)
    if notice is not None and notice["status"] == "SENT":
        notice["status"] = "CURED"
        touch(notice)
    case["status"] = "CURED"
    touch(case)
    # record_payment touches the loan once, covering both field mutations.
    loan["status"] = "CURRENT"
    entry = record_payment(case, loan, body["amount_cents"])
    return object_response(ledger_out(entry), 201)


@bp.post("/recovery-cases/<cid>/ledger-entries")
def create_ledger_entry(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    body = validate_body({
        "kind": ("str", True, calc.MANUAL_LEDGER_KINDS),
        "amount_cents": ("pos_int", True, None),
        "memo": ("str", False, None),
    })
    entry = new_ledger_entry(case["id"], body["kind"], body["amount_cents"],
                             memo=body.get("memo", ""))
    return object_response(ledger_out(entry), 201)


@bp.get("/recovery-cases/<cid>/ledger-entries")
def list_ledger_entries(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    return list_response(calc.case_entries(cid), ledger_out)
