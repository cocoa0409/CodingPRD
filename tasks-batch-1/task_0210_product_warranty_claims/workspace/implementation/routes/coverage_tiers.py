"""Coverage tier endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import ok_array, ok_object
from services import common
from services.registration_svc import mint_common, public

bp = Blueprint("coverage_tiers", __name__)

TIER_NAMES = {"BASE", "SILVER", "GOLD", "PLATINUM"}
DEPRECIATION_METHODS = {"STRAIGHT_LINE", "DECLINING_BALANCE"}
PREMIUM_REFUND_METHODS = {"PRO_RATA", "SHORT_RATE"}


@bp.post("/coverage-tiers")
def create_coverage_tier():
    require_roles(["WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["product_id", "tier_name", "extension_months",
                                 "price_cents", "coverage_cap_cents", "depreciation_method"])
    product_id = common.require_str(body, "product_id")
    tier_name = common.require_enum(body, "tier_name", TIER_NAMES)
    extension_months = common.require_int(body, "extension_months", minimum=0)
    price_cents = common.require_int(body, "price_cents", minimum=0)
    coverage_cap_cents = common.require_int(body, "coverage_cap_cents", minimum=1)
    depreciation_method = common.require_enum(body, "depreciation_method", DEPRECIATION_METHODS)
    refund_eligible = common.require_bool(body, "refund_eligible", default=True)
    premium_refund_method = body.get("premium_refund_method")
    if premium_refund_method is None:
        premium_refund_method = "PRO_RATA"
    elif premium_refund_method not in PREMIUM_REFUND_METHODS:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "premium_refund_method must be PRO_RATA or SHORT_RATE")

    # existence of referenced product (left-to-right; body ref)
    if product_id not in db.products:
        raise APIError(ERR_NOT_FOUND, 404, "Product not found")

    # unique per (product_id, tier_name)
    for t in db.coverage_tiers.values():
        if t["product_id"] == product_id and t["tier_name"] == tier_name:
            raise APIError(ERR_INVALID_REQUEST, 400,
                           "tier_name already exists for this product")

    tier = {
        "product_id": product_id,
        "tier_name": tier_name,
        "extension_months": extension_months,
        "price_cents": price_cents,
        "coverage_cap_cents": coverage_cap_cents,
        "depreciation_method": depreciation_method,
        "refund_eligible": refund_eligible,
        "premium_refund_method": premium_refund_method,
        "status": "ACTIVE",
    }
    mint_common(tier)
    db.coverage_tiers[tier["id"]] = tier
    return ok_object(public(tier), 201)


@bp.get("/coverage-tiers/<tid>")
def get_coverage_tier(tid):
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    tier = db.coverage_tiers.get(tid)
    if tier is None:
        raise APIError(ERR_NOT_FOUND, 404, "CoverageTier not found")
    return ok_object(public(tier))


@bp.get("/coverage-tiers")
def list_coverage_tiers():
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    limit, offset = common.parse_pagination()
    product_id = request.args.get("product_id")
    rows = list(db.coverage_tiers.values())
    if product_id is not None:
        rows = [t for t in rows if t["product_id"] == product_id]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(t) for t in page], limit, offset, total)
