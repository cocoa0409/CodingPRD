"""Resolution endpoints (§3.11). Branching fork by path."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common, calc

bp = Blueprint("resolutions", __name__)

PATHS = {"PAYOFF", "SHORT_SALE", "FORECLOSURE"}
READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}


def _active_deferral_exists(loan_id):
    for d in db.nbs_deferrals.values():
        if d["loan_id"] == loan_id and d["status"] == "ACTIVE":
            return True
    return False


def _compute_lesser_of(loan, path, appraised_at_resolution_cents):
    if path == "SHORT_SALE":
        basis = appraised_at_resolution_cents
    else:
        basis = loan["appraised_value_cents"]
    return calc.lesser_of_payoff(loan["principal_balance_cents"], basis)


@bp.route("/resolutions", methods=["POST"])
def create_resolution():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "path"])
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    common.require_enum(body, "path", PATHS)
    appraised = body.get("appraised_at_resolution_cents")
    if appraised is not None:
        if isinstance(appraised, bool) or not isinstance(appraised, int) or appraised <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "appraised_at_resolution_cents must be > 0")
    if body["path"] == "SHORT_SALE" and appraised is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "SHORT_SALE requires appraised_at_resolution_cents")

    # an ACTIVE deferral blocks a resolution
    if _active_deferral_exists(loan["id"]):
        raise errors.err(errors.ERR_DEFERRAL_ACTIVE, "Loan has an active NBS deferral")
    # state: loan must be DUE_AND_PAYABLE
    if loan["disposition_status"] != "DUE_AND_PAYABLE":
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not due-and-payable")

    payoff, deficiency = _compute_lesser_of(loan, body["path"], appraised)
    rec = {
        "loan_id": loan["id"],
        "path": body["path"],
        "appraised_at_resolution_cents": appraised,
        "payoff_amount_cents": payoff,
        "deficiency_cents": deficiency,
        "status": "INITIATED",
    }
    db.stamp_create(rec)
    db.resolutions[rec["id"]] = rec
    loan["disposition_status"] = "IN_RESOLUTION"
    db.touch(loan)
    return success(public(rec), status=201)


@bp.route("/resolutions/<resolution_id>", methods=["GET"])
def get_resolution(resolution_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.resolutions.get(resolution_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resolution not found")
    return success(public(rec))


@bp.route("/resolutions", methods=["GET"])
def list_resolutions():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.resolutions.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/resolutions/<resolution_id>/settle", methods=["POST"])
def settle(resolution_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    rec = db.resolutions.get(resolution_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resolution not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    # body well-formedness for SHORT_SALE settle
    if rec["path"] == "SHORT_SALE" and rec.get("appraised_at_resolution_cents") is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "SHORT_SALE requires appraised_at_resolution_cents")
    if rec["status"] != "INITIATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Resolution not INITIATED")
    if loan["disposition_status"] != "IN_RESOLUTION":
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not in resolution")

    path = rec["path"]
    if path == "PAYOFF":
        # balance considered satisfied; deficiency 0
        capped = calc.round_half_up(calc.NON_RECOURSE_FACTOR_PCT * loan["appraised_value_cents"] / 100)
        rec["payoff_amount_cents"] = min(loan["principal_balance_cents"], capped)
        rec["deficiency_cents"] = 0
    elif path == "SHORT_SALE":
        payoff, deficiency = calc.lesser_of_payoff(
            loan["principal_balance_cents"], rec["appraised_at_resolution_cents"])
        rec["payoff_amount_cents"] = payoff
        rec["deficiency_cents"] = deficiency
    else:  # FORECLOSURE
        payoff, deficiency = calc.lesser_of_payoff(
            loan["principal_balance_cents"], loan["appraised_value_cents"])
        rec["payoff_amount_cents"] = payoff
        rec["deficiency_cents"] = deficiency

    rec["status"] = "SETTLED"
    db.touch(rec)
    loan["disposition_status"] = "TERMINATED"
    loan["available_line_of_credit_cents"] = 0
    db.touch(loan)
    return success(public(rec))


@bp.route("/resolutions/<resolution_id>/cancel", methods=["POST"])
def cancel(resolution_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    rec = db.resolutions.get(resolution_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resolution not found")
    if rec["status"] != "INITIATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Resolution not INITIATED")
    loan = db.loans.get(rec["loan_id"])
    rec["status"] = "CANCELLED"
    db.touch(rec)
    if loan is not None and loan["disposition_status"] == "IN_RESOLUTION":
        loan["disposition_status"] = "DUE_AND_PAYABLE"
        db.touch(loan)
    return success(public(rec))
