"""Deficiency estimate, notices, and post-sale settlement (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import store, base_fields, touch, get_or_404, sorted_all, now
from errors import (
    ApiError, ERR_INVALID_CASE_STATE, ERR_INVALID_DEFICIENCY_STATE,
    ERR_FORBIDDEN_OWNERSHIP, ERR_DEFICIENCY_WINDOW_EXPIRED,
)
from middleware import require_roles, ALL_ROLES
from response import object_response, list_response
from serializers import deficiency_out
from services import calc
from services.transitions import new_ledger_entry, record_payment
from util import validate_body

bp = Blueprint("deficiency", __name__)


def _case_loan(case):
    return store.loan_accounts[case["loan_account_id"]]


@bp.get("/recovery-cases/<cid>/deficiency-estimate")
def deficiency_estimate(cid):
    require_roles(*ALL_ROLES)
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    # Readable at any time after the case reaches COLLATERAL_SECURED — before
    # that there is no appraisal on file to project proceeds from.
    if case["condition_grade"] is None:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       "Estimate is available only after the collateral is secured")
    loan = _case_loan(case)
    deficiency, surplus = calc.deficiency_amounts(case, loan, "PROVISIONAL")
    _proceeds, basis = calc.provisional_proceeds(case)
    return object_response({
        "estimated_deficiency_cents": deficiency,
        "estimated_surplus_cents": surplus,
        "basis": basis,
    })


@bp.post("/recovery-cases/<cid>/deficiency-notices")
def create_deficiency_notice(cid):
    require_roles("RecoveryManager")
    case = get_or_404(store.recovery_cases, cid, "RecoveryCase")
    validate_body({})
    sale = calc.case_certified_sale(cid)
    if case["status"] != "SALE_CONFIRMED" or sale is None:
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       "Deficiency notice requires a CERTIFIED sale on a "
                       "SALE_CONFIRMED case")
    loan = _case_loan(case)
    deficiency, surplus = calc.deficiency_amounts(case, loan, "FINAL")
    notice = base_fields()
    notice.update({
        "recovery_case_id": case["id"],
        "status": "DRAFT",
        "deficiency_amount_cents": deficiency,
        "surplus_cents": surplus,
        "paid_cents": 0,
        "sent_at": None,
        "_seq": store.next_seq(),
    })
    store.deficiency_notices[notice["id"]] = notice
    return object_response(deficiency_out(notice), 201)


@bp.get("/recovery-cases/<cid>/deficiency-notices")
def list_deficiency_notices(cid):
    require_roles(*ALL_ROLES)
    get_or_404(store.recovery_cases, cid, "RecoveryCase")
    rows = [n for n in sorted_all(store.deficiency_notices)
            if n["recovery_case_id"] == cid]
    return list_response(rows, deficiency_out)


def _notice_and_case(nid):
    notice = get_or_404(store.deficiency_notices, nid, "DeficiencyNotice")
    case = store.recovery_cases[notice["recovery_case_id"]]
    return notice, case


@bp.post("/deficiency-notices/<nid>/send")
def send_notice(nid):
    require_roles("RecoveryManager")
    notice, case = _notice_and_case(nid)
    validate_body({})
    if notice["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_DEFICIENCY_STATE, 409,
                       f"Notice status {notice['status']} does not permit send")
    if case["status"] != "SALE_CONFIRMED":
        raise ApiError(ERR_INVALID_CASE_STATE, 409,
                       f"Case status {case['status']} does not permit notice send")
    if now() > case["sold_at"] + timedelta(days=calc.DEFICIENCY_NOTICE_DAYS):
        raise ApiError(ERR_DEFICIENCY_WINDOW_EXPIRED, 422,
                       "The statutory deficiency-notice window has expired")
    notice["status"] = "SENT"
    notice["sent_at"] = now()
    touch(notice)
    case["status"] = "DEFICIENCY_NOTICED"
    touch(case)
    return object_response(deficiency_out(notice))


@bp.post("/deficiency-notices/<nid>/dispute")
def dispute_notice(nid):
    user_id, _role = require_roles("Borrower")
    notice, case = _notice_and_case(nid)
    if _case_loan(case)["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")
    validate_body({})
    if notice["status"] != "SENT":
        raise ApiError(ERR_INVALID_DEFICIENCY_STATE, 409,
                       f"Notice status {notice['status']} does not permit dispute")
    notice["status"] = "DISPUTED"
    touch(notice)
    return object_response(deficiency_out(notice))


@bp.post("/deficiency-notices/<nid>/revise")
def revise_notice(nid):
    require_roles("RecoveryManager")
    notice, case = _notice_and_case(nid)
    body = validate_body({
        "adjustment_cents": ("int", True, None),
        "reason": ("str", True, None),
    })
    if notice["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_DEFICIENCY_STATE, 409,
                       f"Notice status {notice['status']} does not permit revise")
    notice["deficiency_amount_cents"] = max(
        0, notice["deficiency_amount_cents"] + body["adjustment_cents"])
    notice["status"] = "SENT"
    touch(notice)
    return object_response(deficiency_out(notice))


@bp.post("/deficiency-notices/<nid>/waive")
def waive_notice(nid):
    require_roles("ComplianceOfficer")
    notice, case = _notice_and_case(nid)
    validate_body({})
    if notice["status"] not in ("SENT", "DISPUTED"):
        raise ApiError(ERR_INVALID_DEFICIENCY_STATE, 409,
                       f"Notice status {notice['status']} does not permit waive")
    notice["status"] = "WAIVED"
    touch(notice)
    if notice["surplus_cents"] > 0:
        # The surplus owed to the borrower is settled by a REFUND entry.
        new_ledger_entry(case["id"], "REFUND", notice["surplus_cents"])
    return object_response(deficiency_out(notice))


@bp.post("/deficiency-notices/<nid>/record-payment")
def record_deficiency_payment(nid):
    user_id, _role = require_roles("Borrower")
    notice, case = _notice_and_case(nid)
    loan = _case_loan(case)
    if loan["borrower_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Caller does not own the target case")
    body = validate_body({
        "amount_cents": ("pos_int", True, None),
    })
    if notice["status"] not in ("SENT", "DISPUTED"):
        raise ApiError(ERR_INVALID_DEFICIENCY_STATE, 409,
                       f"Notice status {notice['status']} does not permit payment")
    notice["paid_cents"] += body["amount_cents"]
    # Partial payments change the numbers, not the state.
    if notice["paid_cents"] >= notice["deficiency_amount_cents"]:
        notice["status"] = "PAID"
    touch(notice)
    record_payment(case, loan, body["amount_cents"])
    return object_response(deficiency_out(notice))
