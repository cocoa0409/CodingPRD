"""Coupon endpoints nested under a promotion (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_field,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)

bp = Blueprint("coupons", __name__)

USE_MODES = {"SINGLE_USE", "MULTI_USE"}


@bp.post("/promotions/<promotion_id>/coupons")
@require_roles("MerchantAdmin")
def create_coupon(promotion_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        body = require_json_object(request.get_json(silent=True))
        code = require_str(body, "code")
        use_mode = require_field(body, "use_mode")
        if use_mode not in USE_MODES:
            raise err("ERR_INVALID_REQUEST", "Invalid use_mode")
        max_total = body.get("max_total_redemptions")
        if use_mode == "MULTI_USE":
            if max_total is None:
                raise err(
                    "ERR_INVALID_REQUEST",
                    "max_total_redemptions required for MULTI_USE",
                )
            if isinstance(max_total, bool) or not isinstance(max_total, int):
                raise err("ERR_INVALID_REQUEST", "max_total_redemptions must be an integer")
            if max_total <= 0:
                raise err("ERR_INVALID_REQUEST", "max_total_redemptions must be > 0")
        else:
            # SINGLE_USE: cap treated as 1; store as-is/null.
            max_total = None

        # Uniqueness: coupon code case-insensitive across all coupons (priority 6).
        for c in db.coupons.values():
            if c["code"].lower() == code.lower():
                raise err("ERR_DUPLICATE", "Coupon code already exists")

        rec = new_record(
            {
                "promotion_id": promotion_id,
                "code": code,
                "use_mode": use_mode,
                "max_total_redemptions": max_total,
                "redeemed_count": 0,
                "status": "ENABLED",
            }
        )
        db.coupons[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/promotions/<promotion_id>/coupons")
@require_roles("MerchantAdmin", "Shopper")
def list_coupons(promotion_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        limit, offset = paginate(request.args)
        status = request.args.get("status")
        items = [c for c in db.coupons.values() if c["promotion_id"] == promotion_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(c) for c in page], limit, offset, total)


@bp.get("/promotions/<promotion_id>/coupons/<coupon_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_coupon(promotion_id, coupon_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        c = db.coupons.get(coupon_id)
        if not c or c["promotion_id"] != promotion_id:
            raise err("ERR_NOT_FOUND", "Coupon not found")
        return success(serialize(c), 200)


@bp.post("/promotions/<promotion_id>/coupons/<coupon_id>/disable")
@require_roles("MerchantAdmin")
def disable_coupon(promotion_id, coupon_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        c = db.coupons.get(coupon_id)
        if not c or c["promotion_id"] != promotion_id:
            raise err("ERR_NOT_FOUND", "Coupon not found")
        if c["status"] != "ENABLED":
            raise err("ERR_INVALID_STATE", "Coupon is not ENABLED")
        c["status"] = "DISABLED"
        touch(c)
        return success(serialize(c), 200)


@bp.post("/promotions/<promotion_id>/coupons/<coupon_id>/enable")
@require_roles("MerchantAdmin")
def enable_coupon(promotion_id, coupon_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        c = db.coupons.get(coupon_id)
        if not c or c["promotion_id"] != promotion_id:
            raise err("ERR_NOT_FOUND", "Coupon not found")
        if c["status"] != "DISABLED":
            raise err("ERR_INVALID_STATE", "Coupon is not DISABLED")
        if promo["status"] == "ARCHIVED":
            raise err("ERR_INVALID_STATE", "Parent promotion is ARCHIVED")
        c["status"] = "ENABLED"
        touch(c)
        return success(serialize(c), 200)
