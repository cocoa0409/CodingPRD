"""Price plans, promotions, coupons."""
from flask import Blueprint, request, g

from auth import require_role
from common import (
    stamp_new, touch, require_dict, get_str, get_int, get_bool, get_enum,
    get_dt, validate_window, pagination_params, paginate,
)
from clock import clock
from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
    ERR_PRICE_PLAN_NOT_CANCELLABLE, ERR_PROMOTION_NOT_CANCELLABLE,
    ERR_STALE_PRODUCT_VERSION,
)
from lookup import get_product, get_price_plan, get_promotion, get_coupon
from inventory import product_inventory_rollup
from response import success, list_response
from serializers import ser_price_plan, ser_promotion, ser_coupon, ser_clip

bp = Blueprint("pricing", __name__)


def derive_window_status(rec):
    """Derive SCHEDULED/ACTIVE/EXPIRED from the clock for a windowed entity.
    CANCELLED is terminal and never overridden."""
    if rec["status"] == "CANCELLED":
        return "CANCELLED"
    now = clock.now()
    if now >= rec["_effective_end_dt"]:
        return "EXPIRED"
    if now >= rec["_effective_start_dt"]:
        return "ACTIVE"
    return "SCHEDULED"


def project_status(rec, ser):
    out = ser(rec)
    out["status"] = derive_window_status(rec)
    return out


# ---------------- Price Plans ----------------

@bp.route("/price-plans", methods=["POST"])
def create_price_plan():
    require_role("PriceManager", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    # FK existence first
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    product = get_product(product_id)

    ad_price = get_int(body, "ad_price_cents", min_value=0)
    start = get_dt(body, "effective_start")
    end = get_dt(body, "effective_end")
    expected_version = get_int(body, "expected_product_version")

    # window validity (priority 7)
    validate_window(start, end)

    # OCC (priority 13) — last, immediately before version bump
    if expected_version != product["version"]:
        raise ApiError(ERR_STALE_PRODUCT_VERSION[0], ERR_STALE_PRODUCT_VERSION[1], "stale product version")

    rec = stamp_new({
        "product_id": product_id,
        "ad_price_cents": ad_price,
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "status": "SCHEDULED",
        "_effective_start_dt": start,
        "_effective_end_dt": end,
    })
    db.price_plans[rec["id"]] = rec
    # create bumps the product version (and rollup/updated_at per §2.6)
    touch(product)
    product_inventory_rollup(product)
    return success(project_status(rec, ser_price_plan), status=201)


@bp.route("/price-plans/<pid>", methods=["GET"])
def get_price_plan_route(pid):
    require_role("PriceManager", "StoreManager", "Cashier")
    pp = get_price_plan(pid)
    return success(project_status(pp, ser_price_plan))


@bp.route("/price-plans/<pid>/cancel", methods=["POST"])
def cancel_price_plan(pid):
    require_role("PriceManager", "StoreManager")
    pp = get_price_plan(pid)
    cur = derive_window_status(pp)
    if cur not in ("SCHEDULED", "ACTIVE"):
        raise ApiError(ERR_PRICE_PLAN_NOT_CANCELLABLE[0], ERR_PRICE_PLAN_NOT_CANCELLABLE[1], "price plan not cancellable")
    pp["status"] = "CANCELLED"
    touch(pp)
    return success(project_status(pp, ser_price_plan))


# ---------------- Promotions ----------------

@bp.route("/promotions", methods=["POST"])
def create_promotion():
    require_role("PriceManager", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    get_product(product_id)

    promo_type = get_enum(body, "promo_type", {"PERCENT_OFF", "BOGO", "FIXED_OFF"})
    percent_off = get_int(body, "percent_off_bps", required=False, default=None, min_value=0, max_value=10000)
    fixed_off = get_int(body, "fixed_off_cents", required=False, default=None, min_value=0)
    min_qty = get_int(body, "min_qty", required=False, default=1, min_value=1)
    stackable = get_bool(body, "stackable", required=False, default=False)
    start = get_dt(body, "effective_start")
    end = get_dt(body, "effective_end")

    # type-specific required fields
    if promo_type == "PERCENT_OFF":
        if percent_off is None:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "percent_off_bps required for PERCENT_OFF")
    elif promo_type == "FIXED_OFF":
        if fixed_off is None:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "fixed_off_cents required for FIXED_OFF")

    validate_window(start, end)

    rec = stamp_new({
        "product_id": product_id,
        "promo_type": promo_type,
        "percent_off_bps": percent_off,
        "fixed_off_cents": fixed_off,
        "min_qty": min_qty,
        "stackable": stackable,
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "status": "SCHEDULED",
        "_effective_start_dt": start,
        "_effective_end_dt": end,
    })
    db.promotions[rec["id"]] = rec
    return success(project_status(rec, ser_promotion), status=201)


@bp.route("/promotions/<pid>", methods=["GET"])
def get_promotion_route(pid):
    require_role("PriceManager", "StoreManager", "Cashier")
    pr = get_promotion(pid)
    return success(project_status(pr, ser_promotion))


@bp.route("/promotions/<pid>/cancel", methods=["POST"])
def cancel_promotion(pid):
    require_role("PriceManager", "StoreManager")
    pr = get_promotion(pid)
    cur = derive_window_status(pr)
    if cur not in ("SCHEDULED", "ACTIVE"):
        raise ApiError(ERR_PROMOTION_NOT_CANCELLABLE[0], ERR_PROMOTION_NOT_CANCELLABLE[1], "promotion not cancellable")
    pr["status"] = "CANCELLED"
    touch(pr)
    return success(project_status(pr, ser_promotion))


# ---------------- Coupons ----------------

@bp.route("/coupons", methods=["POST"])
def create_coupon():
    require_role("PriceManager", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    get_product(product_id)

    code = get_str(body, "code")
    discount = get_int(body, "discount_cents", min_value=1)
    min_spend = get_int(body, "min_spend_cents", required=False, default=0, min_value=0)
    stackable = get_bool(body, "stackable", required=False, default=False)
    start = get_dt(body, "effective_start")
    end = get_dt(body, "effective_end")

    # uniqueness
    for c in db.coupons.values():
        if c["code"] == code:
            raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "coupon code already exists")

    validate_window(start, end)

    rec = stamp_new({
        "code": code,
        "product_id": product_id,
        "discount_cents": discount,
        "min_spend_cents": min_spend,
        "stackable": stackable,
        "effective_start": body["effective_start"],
        "effective_end": body["effective_end"],
        "_effective_start_dt": start,
        "_effective_end_dt": end,
    })
    db.coupons[rec["id"]] = rec
    return success(ser_coupon(rec), status=201)


@bp.route("/coupons", methods=["GET"])
def list_coupons():
    require_role("PriceManager", "StoreManager", "Cashier")
    limit, offset = pagination_params(request.args)
    items = list(db.coupons.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [c for c in items if c["product_id"] == product_id]
    page, total = paginate(items, limit, offset)
    return list_response([ser_coupon(c) for c in page], limit, offset, total)


@bp.route("/coupons/<cid>", methods=["GET"])
def get_coupon_route(cid):
    require_role("PriceManager", "StoreManager", "Cashier")
    c = get_coupon(cid)
    return success(ser_coupon(c))


@bp.route("/coupons/<cid>/clipped-coupons", methods=["GET"])
def list_coupon_clips(cid):
    require_role("PriceManager", "StoreManager", "Cashier")
    get_coupon(cid)
    limit, offset = pagination_params(request.args)
    items = [cc for cc in db.clipped_coupons.values() if cc["coupon_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [cc for cc in items if cc["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_clip(cc) for cc in page], limit, offset, total)
