"""ApyTier configuration — PRD §3.11.

ApyTier is reference config: id + created_at only (no updated_at, no version).
"""
from flask import Blueprint, request

from db import db, new_id, now_iso
from middleware import require_roles
from response import object_response
from services.validate import get_body, require_fields, require_enum, require_nonneg_int
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("apy_tiers", __name__)

PRODUCT_TYPES = {"CHECKING", "SAVINGS"}


def serialize_tier(t):
    return {k: v for k, v in t.items() if k != "_seq"}


@bp.route("/apy-tiers", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_tier():
    body = get_body()
    require_fields(body, "code", "product_type", "min_balance_cents", "annual_rate_bps")
    product_type = require_enum(body, "product_type", PRODUCT_TYPES)

    min_balance = body["min_balance_cents"]
    if not isinstance(min_balance, int) or isinstance(min_balance, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "min_balance_cents must be an integer")

    rate = body["annual_rate_bps"]
    # ApyTier annual_rate_bps must be >= 0 (PRD §2.9 -> ERR_INVALID_AMOUNT).
    require_nonneg_int(rate, "annual_rate_bps")

    code = body["code"]
    if not isinstance(code, str) or code.strip() == "":
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "code must be a non-empty string")

    tier = {
        "id": new_id(),
        "created_at": now_iso(),
        "code": code,
        "product_type": product_type,
        "min_balance_cents": min_balance,
        "annual_rate_bps": rate,
        "_seq": db.next_seq(),
    }
    db.apy_tiers[tier["id"]] = tier
    return object_response(serialize_tier(tier), status=201)


@bp.route("/apy-tiers", methods=["GET"])
@require_roles("ComplianceOfficer", "Teller", "AccountHolder")
def list_tiers():
    product_type = request.args.get("product_type")
    rows = list(db.apy_tiers.values())
    if product_type is not None:
        rows = [t for t in rows if t["product_type"] == product_type]
    return paged_list(rows, serializer=serialize_tier)
