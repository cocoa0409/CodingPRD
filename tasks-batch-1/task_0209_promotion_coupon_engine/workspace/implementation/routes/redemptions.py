"""CouponRedemption read endpoints (PRD §3.11)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_identity, require_roles
from response import success, success_list
from services.common import paginate, serialize, sort_by_created

bp = Blueprint("redemptions", __name__)


@bp.get("/redemptions/<redemption_id>")
@require_roles("MerchantAdmin", "Shopper")
def get_redemption(redemption_id):
    with db.lock:
        user_id, role = get_identity()
        r = db.coupon_redemptions.get(redemption_id)
        if not r:
            raise err("ERR_NOT_FOUND", "Redemption not found")
        if role == "Shopper" and r["customer_id"] != user_id:
            raise err("ERR_FORBIDDEN_ROLE", "Not the owning customer")
        return success(serialize(r), 200)


@bp.get("/redemptions")
@require_roles("MerchantAdmin")
def list_redemptions():
    with db.lock:
        limit, offset = paginate(request.args)
        coupon_id = request.args.get("coupon_id")
        promotion_id = request.args.get("promotion_id")
        customer_id = request.args.get("customer_id")
        cart_id = request.args.get("cart_id")
        status = request.args.get("status")
        items = list(db.coupon_redemptions.values())
        if coupon_id is not None:
            items = [r for r in items if r["coupon_id"] == coupon_id]
        if promotion_id is not None:
            items = [r for r in items if r["promotion_id"] == promotion_id]
        if customer_id is not None:
            items = [r for r in items if r["customer_id"] == customer_id]
        if cart_id is not None:
            items = [r for r in items if r["cart_id"] == cart_id]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(r) for r in page], limit, offset, total)
