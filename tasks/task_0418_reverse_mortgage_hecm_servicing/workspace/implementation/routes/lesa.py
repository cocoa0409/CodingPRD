"""LesaSetAside endpoints (§3.3)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common

bp = Blueprint("lesa", __name__)

FUNDING_MODES = {"FULLY_FUNDED", "PARTIALLY_FUNDED"}
READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}
GET_ONE_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"}


@bp.route("/lesa-set-asides", methods=["POST"])
def create_lesa():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "funding_mode", "annual_property_charge_cents",
                                 "life_expectancy_years"])
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    common.require_enum(body, "funding_mode", FUNDING_MODES)
    charge = common.require_positive_int(body, "annual_property_charge_cents")
    ley = body["life_expectancy_years"]
    if isinstance(ley, bool) or not isinstance(ley, int) or ley < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "life_expectancy_years must be >= 1")
    rec = {
        "loan_id": body["loan_id"],
        "funding_mode": body["funding_mode"],
        "annual_property_charge_cents": charge,
        "life_expectancy_years": ley,
        "initial_amount_cents": 0,
        "drawn_cents": 0,
        "remaining_cents": 0,
        "status": "FUNDED",
    }
    db.stamp_create(rec)
    db.lesa_set_asides[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/lesa-set-asides/<lesa_id>", methods=["GET"])
def get_lesa(lesa_id):
    _, role = get_user_context()
    require_role(role, GET_ONE_ROLES)
    rec = db.lesa_set_asides.get(lesa_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "LesaSetAside not found")
    return success(public(rec))


@bp.route("/lesa-set-asides", methods=["GET"])
def list_lesa():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.lesa_set_asides.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)
