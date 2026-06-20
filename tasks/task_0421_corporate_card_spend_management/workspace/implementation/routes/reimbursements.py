"""Out-of-pocket reimbursement claims (PRD §3.7)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, require_positive_int, paginate, serialize,
    reward_account_for, q as _q, filter_items as _filter,
)
from decimal import Decimal

from services.calculations import compute_reimbursable, round_half_up

bp = Blueprint("reimbursements", __name__)


@bp.route("/reimbursement-claims", methods=["POST"])
def create_claim():
    _, role = get_user_context()
    require_role(role, {"CardholderEmployee", "FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "employee_id", "gl_account_id",
                          "merchant_name", "amount_cents", "receipt_amount_cents"])
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        get_or_404(db.employees, body["employee_id"])
        get_or_404(db.gl_accounts, body["gl_account_id"])
        amount = require_positive_int(body, "amount_cents")
        receipt_amount = require_positive_int(body, "receipt_amount_cents")
        claim = {
            "company_id": body["company_id"],
            "employee_id": body["employee_id"],
            "gl_account_id": body["gl_account_id"],
            "merchant_name": body["merchant_name"],
            "amount_cents": amount,
            "receipt_amount_cents": receipt_amount,
            "reimbursable_cents": 0,
            "status": "DRAFT",
        }
        stamp_create(claim)
        db.reimbursement_claims[claim["id"]] = claim
        return success(serialize(claim), 201)


@bp.route("/reimbursement-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.reimbursement_claims, claim_id)), 200)


@bp.route("/reimbursement-claims", methods=["GET"])
def list_claims():
    get_user_context()
    with LOCK:
        items = list(db.reimbursement_claims.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "employee_id": _q("employee_id"),
            "gl_account_id": _q("gl_account_id"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/reimbursement-claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    user_id, role = get_user_context()
    require_role(role, {"CardholderEmployee"})
    get_json_body()
    with LOCK:
        claim = get_or_404(db.reimbursement_claims, claim_id)
        if claim["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Claim is not DRAFT.")
        if user_id != claim["employee_id"]:
            raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Only the claimant may submit.")
        claim["status"] = "SUBMITTED"
        touch(claim)
        return success(serialize(claim), 200)


@bp.route("/reimbursement-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    get_json_body()
    with LOCK:
        claim = get_or_404(db.reimbursement_claims, claim_id)
        if claim["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED.")
        if user_id == claim["employee_id"]:
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot approve your own claim.")
        gl = db.gl_accounts.get(claim["gl_account_id"])
        if gl is None or gl["status"] != "ACTIVE":
            raise errors.err(errors.ERR_GL_CODE_REQUIRED, "An active GL code is required.")
        claim["reimbursable_cents"] = compute_reimbursable(claim)
        claim["status"] = "APPROVED"
        touch(claim)
        return success(serialize(claim), 200)


@bp.route("/reimbursement-claims/<claim_id>/reject", methods=["POST"])
def reject_claim(claim_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    get_json_body()
    with LOCK:
        claim = get_or_404(db.reimbursement_claims, claim_id)
        if claim["status"] != "SUBMITTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED.")
        if user_id == claim["employee_id"]:
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot reject your own claim.")
        claim["status"] = "REJECTED"
        touch(claim)
        return success(serialize(claim), 200)


@bp.route("/reimbursement-claims/<claim_id>/revise", methods=["POST"])
def revise_claim(claim_id):
    user_id, role = get_user_context()
    require_role(role, {"CardholderEmployee"})
    get_json_body()
    with LOCK:
        claim = get_or_404(db.reimbursement_claims, claim_id)
        if claim["status"] != "REJECTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Claim is not REJECTED.")
        if user_id != claim["employee_id"]:
            raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Only the claimant may revise.")
        claim["status"] = "DRAFT"
        touch(claim)
        return success(serialize(claim), 200)


@bp.route("/reimbursement-claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        claim = get_or_404(db.reimbursement_claims, claim_id)
        if claim["status"] != "APPROVED":
            raise errors.err(errors.ERR_INVALID_STATE, "Claim is not APPROVED.")
        claim["status"] = "PAID"
        touch(claim)
        # CASCADE: reward accrues on reimbursable_cents at company default rate
        # (round half up; the per-transaction cap does NOT apply to reimbursements).
        company = db.companies.get(claim["company_id"])
        reward = round_half_up(
            Decimal(claim["reimbursable_cents"])
            * Decimal(company["reward_rate_default_bps"]) / Decimal(10000)
        )
        ra = reward_account_for(claim["company_id"])
        if ra and reward:
            ra["accrued_points_cents"] += reward
            ra["balance_points_cents"] = ra["accrued_points_cents"] - ra["redeemed_points_cents"]
            touch(ra)
        return success(serialize(claim), 200)
