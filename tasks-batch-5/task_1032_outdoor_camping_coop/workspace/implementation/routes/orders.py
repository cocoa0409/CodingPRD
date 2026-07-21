from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_int, opt_bool, fetch,
    authenticate, authorize, require_owner, new_common, touch, serialize,
    sorted_by_created, paginate, round_half_up, ApiError,
    MEMBER_DISCOUNT_PCT, LOYALTY_CENTS_PER_POINT,
    credit_wallet, add_loyalty, add_spend,
)
from decimal import Decimal

bp = Blueprint("orders", __name__)


def _validate_lines(data):
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError("ERR_VALIDATION", "'lines' must be a non-empty array")
    clean = []
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_VALIDATION", "each line must be an object")
        gear_sku_id = req_str(line, "gear_sku_id")
        quantity = req_int(line, "quantity", min_value=1)
        clean.append({"gear_sku_id": gear_sku_id, "quantity": quantity})
    return clean


@bp.route("/coop/sales-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    data = get_body()
    member_id = req_str(data, "member_id")
    lines = _validate_lines(data)
    use_store_credit = opt_bool(data, "use_store_credit", False)

    require_owner(role, uid, member_id)

    member = fetch("members", member_id)
    tier_pct = MEMBER_DISCOUNT_PCT[member["membership_tier"]]

    subtotal = 0
    discount = 0
    for line in lines:
        sku = fetch("gear_skus", line["gear_sku_id"])
        line_gross = sku["retail_price_cents"] * line["quantity"]
        subtotal += line_gross
        discount += round_half_up(Decimal(line_gross) * tier_pct)
    total = subtotal - discount
    loyalty_earned = total // LOYALTY_CENTS_PER_POINT

    order = new_common()
    order.update({
        "member_id": member_id,
        "lines": lines,
        "use_store_credit": use_store_credit,
        "payment_status": "UNPAID",
        "fulfillment_status": "UNFULFILLED",
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "loyalty_points_earned": loyalty_earned,
    })
    db.orders[order["id"]] = order
    return ok(serialize(order), status=201)


@bp.route("/coop/sales-orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    order = fetch("orders", oid)
    require_owner(role, uid, order["member_id"])
    return ok(serialize(order))


@bp.route("/coop/sales-orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", "Members may only list their own orders")
        member_id = uid
    payment_status = request.args.get("payment_status")
    items = list(db.orders.values())
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if payment_status is not None:
        items = [o for o in items if o["payment_status"] == payment_status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)


@bp.route("/coop/sales-orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    order = fetch("orders", oid)
    require_owner(role, uid, order["member_id"])
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", "Order is not UNPAID")
    member = fetch("members", order["member_id"])
    total = order["total_cents"]
    if order["use_store_credit"] and member["store_credit_cents"] < total:
        raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit to pay")

    order["payment_status"] = "PAID"
    touch(order)
    if order["use_store_credit"]:
        credit_wallet(member, -total)
    add_loyalty(member, order["loyalty_points_earned"])
    add_spend(member, total)
    return ok(serialize(order))


@bp.route("/coop/sales-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "UNFULFILLED":
        raise ApiError("ERR_INVALID_STATE", "Order is not UNFULFILLED")
    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    return ok(serialize(order))


@bp.route("/coop/sales-orders/<oid>/return", methods=["POST"])
def return_order(oid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    order = fetch("orders", oid)
    require_owner(role, uid, order["member_id"])
    if order["payment_status"] != "PAID" or order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_PAID", "Order must be PAID and FULFILLED to return")

    order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "RETURNED"
    touch(order)

    member = fetch("members", order["member_id"])
    total = order["total_cents"]
    credit_wallet(member, total)
    add_loyalty(member, -order["loyalty_points_earned"])
    add_spend(member, -total)
    return ok(serialize(order))
