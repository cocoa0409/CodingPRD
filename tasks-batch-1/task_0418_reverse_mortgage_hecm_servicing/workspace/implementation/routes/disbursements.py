"""Disbursement lifecycle (§3.5)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common, ledger

bp = Blueprint("disbursements", __name__)

KINDS = {"INITIAL", "LINE_DRAW", "SCHEDULED"}
ALL_READ = {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"}


@bp.route("/disbursements", methods=["POST"])
def request_disbursement():
    user_id, role = get_user_context()
    require_role(role, {"ServicerOps", "Borrower"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "kind", "requested_amount_cents"])
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if role == "Borrower" and loan["borrower_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only draw against own loan")
    common.require_enum(body, "kind", KINDS)
    amount = common.require_positive_int(body, "requested_amount_cents")
    rec = {
        "loan_id": body["loan_id"],
        "kind": body["kind"],
        "requested_amount_cents": amount,
        "approved_amount_cents": 0,
        "status": "REQUESTED",
    }
    db.stamp_create(rec)
    db.disbursements[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/disbursements/<disbursement_id>", methods=["GET"])
def get_disbursement(disbursement_id):
    user_id, role = get_user_context()
    require_role(role, ALL_READ)
    rec = db.disbursements.get(disbursement_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Disbursement not found")
    if role == "Borrower":
        loan = db.loans.get(rec["loan_id"])
        if loan is None or loan["borrower_id"] != user_id:
            raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only access own draws")
    return success(public(rec))


@bp.route("/disbursements", methods=["GET"])
def list_disbursements():
    _, role = get_user_context()
    require_role(role, ALL_READ)
    limit, offset = common.parse_pagination()
    rows = list(db.disbursements.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/disbursements/<disbursement_id>/approve", methods=["POST"])
def approve(disbursement_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.disbursements.get(disbursement_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Disbursement not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    body = common.get_json_body()
    # body well-formedness: expected_loan_version required, integer
    if "expected_loan_version" not in body or body["expected_loan_version"] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_loan_version is required")
    elv = body["expected_loan_version"]
    if isinstance(elv, bool) or not isinstance(elv, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_loan_version must be an integer")
    # state: transition defined only from REQUESTED
    if rec["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Disbursement not in REQUESTED state")
    # business rules in pinned order:
    # 1) drawable
    if loan["disposition_status"] != "ACTIVE" or loan["servicing_status"] != "CURRENT":
        raise errors.err(errors.ERR_LOAN_NOT_DRAWABLE, "Loan not drawable")
    # 2) draw-type mismatch for LINE_DRAW
    if rec["kind"] == "LINE_DRAW" and loan["draw_type"] != "LINE_OF_CREDIT":
        raise errors.err(errors.ERR_DRAW_TYPE_MISMATCH, "LINE_DRAW requires LINE_OF_CREDIT loan")
    # 3) insufficient line (== allowed)
    if rec["requested_amount_cents"] > loan["available_line_of_credit_cents"]:
        raise errors.err(errors.ERR_INSUFFICIENT_LINE, "Requested amount exceeds available line")
    # 4) OCC stale version
    if elv != loan["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_loan_version does not match loan version")

    rec["approved_amount_cents"] = rec["requested_amount_cents"]
    rec["status"] = "APPROVED"
    db.touch(rec)
    db.touch(loan)  # increments loan.version by 1
    return success(public(rec))


@bp.route("/disbursements/<disbursement_id>/disburse", methods=["POST"])
def disburse(disbursement_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.disbursements.get(disbursement_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Disbursement not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if rec["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Disbursement not in APPROVED state")
    if loan["disposition_status"] != "ACTIVE":
        raise errors.err(errors.ERR_LOAN_NOT_DRAWABLE, "Loan not drawable")
    amount = rec["approved_amount_cents"]
    loan["principal_balance_cents"] += amount
    loan["available_line_of_credit_cents"] -= amount
    ledger.post_entry(loan, "ADVANCE", amount, source_ref_id=rec["id"])
    rec["status"] = "DISBURSED"
    db.touch(rec)
    db.touch(loan)
    return success(public(rec))


@bp.route("/disbursements/<disbursement_id>/reject", methods=["POST"])
def reject(disbursement_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.disbursements.get(disbursement_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Disbursement not found")
    if rec["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Disbursement not in REQUESTED state")
    rec["status"] = "REJECTED"
    rec["approved_amount_cents"] = 0
    db.touch(rec)
    return success(public(rec))


@bp.route("/disbursements/<disbursement_id>/void", methods=["POST"])
def void(disbursement_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.disbursements.get(disbursement_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Disbursement not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if rec["status"] != "DISBURSED":
        raise errors.err(errors.ERR_INVALID_STATE, "Disbursement not in DISBURSED state")
    if loan["disposition_status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not ACTIVE")
    amount = rec["approved_amount_cents"]
    loan["principal_balance_cents"] -= amount
    loan["available_line_of_credit_cents"] += amount
    ledger.post_entry(loan, "REVERSAL", -amount, source_ref_id=rec["id"])
    rec["status"] = "VOIDED"
    db.touch(rec)
    db.touch(loan)
    return success(public(rec))
