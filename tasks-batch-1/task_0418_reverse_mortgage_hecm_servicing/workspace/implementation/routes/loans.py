"""Loan endpoints: create, get, list, originate, post-accrual, payoff-quote,
recompute (§3.2, §3.4, §3.6, §3.12)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common
from services import loan as loan_svc

bp = Blueprint("loans", __name__)

DRAW_TYPES = {"LUMP_SUM", "LINE_OF_CREDIT", "TENURE", "TERM"}
READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}
BORROWER_READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"}


@bp.route("/loans", methods=["POST"])
def create_loan():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["lender_id", "borrower_id", "appraised_value_cents",
                                 "expected_rate_bps", "draw_type"])
    # existence resolved left to right: lender, borrower, optional nbs
    lender = db.lenders.get(body["lender_id"])
    if lender is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lender not found")
    borrower = db.borrowers.get(body["borrower_id"])
    if borrower is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Borrower not found")
    nbs_id = body.get("non_borrowing_spouse_id")
    if nbs_id is not None:
        nbs = db.borrowers.get(nbs_id)
        if nbs is None:
            raise errors.err(errors.ERR_NOT_FOUND, "Non-borrowing spouse not found")

    appraised = common.require_positive_int(body, "appraised_value_cents")
    rate = body["expected_rate_bps"]
    if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_rate_bps must be >= 0")
    draw_type = body["draw_type"]
    if draw_type not in DRAW_TYPES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid draw_type")

    mip = common.optional_int(body, "annual_mip_rate_bps", 50)
    if mip < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "annual_mip_rate_bps must be >= 0")

    ttm = body.get("tenure_term_months")
    if draw_type == "TERM":
        if ttm is None or isinstance(ttm, bool) or not isinstance(ttm, int) or ttm < 1:
            raise errors.err(errors.ERR_INVALID_REQUEST, "TERM loan requires tenure_term_months >= 1")
    elif ttm is not None:
        if isinstance(ttm, bool) or not isinstance(ttm, int):
            raise errors.err(errors.ERR_INVALID_REQUEST, "tenure_term_months must be an integer")

    ifc = common.optional_int(body, "initial_financed_costs_cents", 0)
    if ifc < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "initial_financed_costs_cents must be >= 0")

    rec = {
        "lender_id": body["lender_id"],
        "borrower_id": body["borrower_id"],
        "non_borrowing_spouse_id": nbs_id,
        "appraised_value_cents": appraised,
        "expected_rate_bps": rate,
        "annual_mip_rate_bps": mip,
        "draw_type": draw_type,
        "tenure_term_months": ttm,
        "initial_financed_costs_cents": ifc,
    }
    rec.update(loan_svc.new_loan_blank_fields())
    db.stamp_create(rec)
    db.loans[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    user_id, role = get_user_context()
    require_role(role, BORROWER_READ_ROLES)
    rec = db.loans.get(loan_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if role == "Borrower" and rec["borrower_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only access own loan")
    return success(public(rec))


@bp.route("/loans", methods=["GET"])
def list_loans():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.loans.values())
    lender_id = request.args.get("lender_id")
    if lender_id is not None:
        rows = [r for r in rows if r["lender_id"] == lender_id]
    borrower_id = request.args.get("borrower_id")
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    nbs_id = request.args.get("non_borrowing_spouse_id")
    if nbs_id is not None:
        rows = [r for r in rows if r.get("non_borrowing_spouse_id") == nbs_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/loans/<loan_id>/originate", methods=["POST"])
def originate_loan(loan_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    rec = db.loans.get(loan_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    loan_svc.originate(rec)
    return success(public(rec))


@bp.route("/loans/<loan_id>/post-accrual", methods=["POST"])
def post_accrual(loan_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps", "System"})
    rec = db.loans.get(loan_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    body = common.get_json_body()
    months = common.require_positive_int(body, "number_of_months")
    loan_svc.post_accrual(rec, months)
    return success(public(rec))


@bp.route("/loans/<loan_id>/payoff-quote", methods=["GET"])
def payoff_quote(loan_id):
    user_id, role = get_user_context()
    require_role(role, BORROWER_READ_ROLES)
    rec = db.loans.get(loan_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if role == "Borrower" and rec["borrower_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only access own loan")
    raw = request.args.get("number_of_months")
    if raw is None:
        months = 0
    else:
        try:
            months = int(raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "number_of_months must be an integer")
        if months < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "number_of_months must be >= 0")
    return success(loan_svc.payoff_quote(rec, months))


@bp.route("/loans/<loan_id>/recompute", methods=["POST"])
def recompute(loan_id):
    _, role = get_user_context()
    require_role(role, {"HudAuditor", "ServicerOps"})
    rec = db.loans.get(loan_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    loan_svc.recompute(rec)
    return success(public(rec))
