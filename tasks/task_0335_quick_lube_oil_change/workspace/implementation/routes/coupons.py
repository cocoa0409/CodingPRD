"""Coupon endpoints (PRD §3.1, §3.5)."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, require_int, require_enum,
                    optional_int, optional_number, require_bool, parse_pagination,
                    paginate, sort_by_created, stamp_create, new_id, touch)
from errors import ApiError, ERR_VALIDATION
from response import success_object, success_array
from services import lookup
from services.serialize import coupon_out

bp = Blueprint("coupons", __name__)

READ_ROLES = ("ShopManager", "ServiceAdvisor")
DISCOUNT_TYPES = {"PERCENT", "FLAT"}


@bp.route("/coupons", methods=["POST"])
def create_coupon():
    require_role("ShopManager")
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    code = require_str(body, "code")
    discount_type = require_enum(body, "discount_type", DISCOUNT_TYPES)
    percent_value = optional_number(body, "percent_value", 0, minimum=0, maximum=1,
                                    min_inclusive=True, max_inclusive=False)
    flat_cents = optional_int(body, "flat_cents", 0, minimum=0)
    min_subtotal = optional_int(body, "min_subtotal_cents", 0, minimum=0)
    stackable = require_bool(body, "stackable_with_fleet", default=False)
    usage_limit = require_int(body, "usage_limit", minimum=1)
    lookup.get_shop(shop_id)
    # Case-sensitive code unique among the shop's currently ACTIVE coupons.
    for c in db.coupons.values():
        if c["shop_id"] == shop_id and c["code"] == code and c["status"] == "ACTIVE":
            raise ApiError(ERR_VALIDATION, 400, "coupon code already active for this shop")
    coupon = {
        "id": new_id(),
        "shop_id": shop_id,
        "code": code,
        "discount_type": discount_type,
        "percent_value": percent_value,
        "flat_cents": flat_cents,
        "min_subtotal_cents": min_subtotal,
        "stackable_with_fleet": stackable,
        "usage_limit": usage_limit,
        "status": "ACTIVE",
    }
    stamp_create(coupon)
    db.coupons[coupon["id"]] = coupon
    return success_object(coupon_out(coupon), 201)


@bp.route("/coupons", methods=["GET"])
def list_coupons():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.coupons.values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        rows = [c for c in rows if c["shop_id"] == shop_id]
    code = request.args.get("code")
    if code is not None:
        rows = [c for c in rows if c["code"] == code]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([coupon_out(c) for c in page], limit, offset, total)


@bp.route("/coupons/<coupon_id>", methods=["GET"])
def get_coupon(coupon_id):
    require_role(*READ_ROLES)
    coupon = lookup.get_coupon(coupon_id)
    return success_object(coupon_out(coupon), 200)


@bp.route("/coupons/<coupon_id>/expire", methods=["POST"])
def expire_coupon(coupon_id):
    require_role("ShopManager")
    coupon = lookup.get_coupon(coupon_id)
    coupon["status"] = "EXPIRED"
    touch(coupon)
    return success_object(coupon_out(coupon), 200)
