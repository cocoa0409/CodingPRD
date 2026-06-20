"""PrincipalLimitFactor config rows (§3.1). Lean entity: id + created_at only."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common

bp = Blueprint("plf", __name__)

READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}


@bp.route("/principal-limit-factors", methods=["POST"])
def create_plf():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["lender_id", "age", "expected_rate_bps", "factor_micros"])
    lender = db.lenders.get(body["lender_id"])
    if lender is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lender not found")
    age = body["age"]
    if isinstance(age, bool) or not isinstance(age, int) or age < 62 or age > 150:
        raise errors.err(errors.ERR_INVALID_REQUEST, "age must be between 62 and 150")
    rate = body["expected_rate_bps"]
    if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_rate_bps must be >= 0")
    factor = body["factor_micros"]
    if isinstance(factor, bool) or not isinstance(factor, int) or factor < 1 or factor > 1000000:
        raise errors.err(errors.ERR_INVALID_REQUEST, "factor_micros must be between 1 and 1000000")
    rec = {
        "lender_id": body["lender_id"],
        "age": age,
        "expected_rate_bps": rate,
        "factor_micros": factor,
    }
    db.stamp_create(rec, with_version=False)
    db.principal_limit_factors[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/principal-limit-factors/<plf_id>", methods=["GET"])
def get_plf(plf_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.principal_limit_factors.get(plf_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "PrincipalLimitFactor not found")
    return success(public(rec))


@bp.route("/principal-limit-factors", methods=["GET"])
def list_plf():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.principal_limit_factors.values())
    lender_id = request.args.get("lender_id")
    if lender_id is not None:
        rows = [r for r in rows if r["lender_id"] == lender_id]
    rate = request.args.get("expected_rate_bps")
    if rate is not None:
        try:
            rate_i = int(rate)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "expected_rate_bps filter must be an integer")
        rows = [r for r in rows if r["expected_rate_bps"] == rate_i]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)
