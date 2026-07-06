"""Order + OrderLine endpoints (parallel payment x fulfillment state)."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, get_pagination, paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_DEPENDENCY_NOT_READY, ERR_INSUFFICIENT_CREDIT, ERR_NOT_FOUND,
)
from services import (
    public, public_list, recompute_order, recompute_tier, release_item,
    settle_consignment_sale, promote_waitlist,
)
import calculations as calc

bp = Blueprint("orders", __name__)

CHANNELS = {"ONLINE", "IN_STORE"}


def _owner_check(role, user_id, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


@bp.route("/shop/orders", methods=["POST"])
def create_order():
    user_id, role = authenticate({"Customer"})
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise err(ERR_INVALID_REQUEST, "customer_id required")
    channel = body.get("channel")
    if channel not in CHANNELS:
        raise err(ERR_INVALID_REQUEST, "channel must be ONLINE or IN_STORE")
    lookup(db.db.customers, customer_id)
    _owner_check(role, user_id, customer_id)
    order = base_fields()
    order.update({
        "customer_id": customer_id,
        "channel": channel,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "shipping_cents": 0,
        "total_cents": 0,
        "points_earned": 0,
        "credit_applied_cents": 0,
    })
    db.db.orders[order["id"]] = order
    return success(public(order), 201)


@bp.route("/shop/orders/<oid>", methods=["GET"])
def read_order(oid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    order = lookup(db.db.orders, oid)
    return success(public(order), 200)


@bp.route("/shop/orders", methods=["GET"])
def list_orders():
    authenticate({"Customer", "StoreClerk", "Manager"})
    limit, offset = get_pagination()
    customer_id = request.args.get("customer_id")
    payment_status = request.args.get("payment_status")
    fulfillment_status = request.args.get("fulfillment_status")
    items = list(db.db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if payment_status is not None:
        items = [o for o in items if o["payment_status"] == payment_status]
    if fulfillment_status is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment_status]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    user_id, role = authenticate({"Customer"})
    order = lookup(db.db.orders, oid)
    body = get_body()
    inv_id = body.get("inventory_item_id")
    if not isinstance(inv_id, str) or not inv_id:
        raise err(ERR_INVALID_REQUEST, "inventory_item_id required")
    item = lookup(db.db.inventory_items, inv_id)
    _owner_check(role, user_id, order["customer_id"])
    # state: fulfillment must be PENDING or RESERVED (still open, not shipped etc.)
    if order["fulfillment_status"] not in ("PENDING", "RESERVED"):
        raise err(ERR_INVALID_STATE, "Order is not open for adding lines")
    # item must be AVAILABLE or ON_DISPLAY
    if item["status"] not in ("AVAILABLE", "ON_DISPLAY"):
        raise err(ERR_INVALID_STATE, "Inventory item is not available for sale")
    line = base_fields()
    line.update({
        "order_id": oid,
        "inventory_item_id": inv_id,
        "qty": 1,
        "unit_price_cents": item["list_price_cents"],
    })
    db.db.order_lines[line["id"]] = line
    # reserve the item
    item["status"] = "RESERVED"
    touch(item)
    # fulfillment PENDING -> RESERVED
    order["fulfillment_status"] = "RESERVED"
    recompute_order(order)
    touch(order)
    return success(public(line), 201)


@bp.route("/shop/orders/<oid>/lines", methods=["GET"])
def list_lines(oid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    lookup(db.db.orders, oid)
    limit, offset = get_pagination()
    items = [l for l in db.db.order_lines.values() if l["order_id"] == oid]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/order-lines/<lid>", methods=["GET"])
def read_line(lid):
    authenticate({"Customer", "StoreClerk", "Manager"})
    line = lookup(db.db.order_lines, lid)
    return success(public(line), 200)


@bp.route("/shop/order-lines", methods=["GET"])
def list_order_lines():
    authenticate({"StoreClerk", "Manager"})
    limit, offset = get_pagination()
    inv_id = request.args.get("inventory_item_id")
    order_id = request.args.get("order_id")
    items = list(db.db.order_lines.values())
    if inv_id is not None:
        items = [l for l in items if l["inventory_item_id"] == inv_id]
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/orders/<oid>/authorize-payment", methods=["POST"])
def authorize_payment(oid):
    user_id, role = authenticate({"Customer"})
    order = lookup(db.db.orders, oid)
    _owner_check(role, user_id, order["customer_id"])
    if order["payment_status"] != "UNPAID":
        raise err(ERR_INVALID_STATE, "Payment is not UNPAID")
    lines = [l for l in db.db.order_lines.values() if l["order_id"] == oid]
    if len(lines) < 1:
        raise err(ERR_INVALID_STATE, "Order has no lines")
    # Payment advances independently of fulfillment (scaffold note); the only
    # blocking fulfillment state is a cancelled order.
    if order["fulfillment_status"] == "CANCELLED":
        raise err(ERR_INVALID_STATE, "Order is cancelled")
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(public(order), 200)


@bp.route("/shop/orders/<oid>/capture-payment", methods=["POST"])
def capture_payment(oid):
    authenticate({"StoreClerk"})
    order = lookup(db.db.orders, oid)
    if order["payment_status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Payment is not AUTHORIZED")
    body = get_body()
    credit_applied = body.get("credit_applied_cents", 0)
    if credit_applied is None:
        credit_applied = 0
    if isinstance(credit_applied, bool) or not isinstance(credit_applied, int) or credit_applied < 0:
        raise err(ERR_INVALID_REQUEST, "credit_applied_cents must be a non-negative integer")
    customer = db.db.customers[order["customer_id"]]
    if credit_applied > customer["store_credit_cents"]:
        raise err(ERR_INSUFFICIENT_CREDIT, "Applied credit exceeds balance")
    order["payment_status"] = "PAID"
    order["credit_applied_cents"] = credit_applied
    customer["store_credit_cents"] -= credit_applied
    points = calc.loyalty_points_earned(order["total_cents"], customer["loyalty_tier"])
    order["points_earned"] = points
    customer["loyalty_points"] += points
    recompute_tier(customer)
    touch(customer)
    touch(order)
    return success(public(order), 200)


@bp.route("/shop/orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    authenticate({"StoreClerk"})
    order = lookup(db.db.orders, oid)
    if order["fulfillment_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Fulfillment is not RESERVED")
    if order["channel"] != "ONLINE":
        raise err(ERR_INVALID_STATE, "Only ONLINE orders can be shipped")
    if order["payment_status"] != "PAID":
        raise err(ERR_DEPENDENCY_NOT_READY, "Payment not settled")
    _complete_fulfillment(order, "SHIPPED")
    return success(public(order), 200)


@bp.route("/shop/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    authenticate({"StoreClerk"})
    order = lookup(db.db.orders, oid)
    if order["fulfillment_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Fulfillment is not RESERVED")
    if order["channel"] != "IN_STORE":
        raise err(ERR_INVALID_STATE, "Only IN_STORE orders can be picked up")
    if order["payment_status"] != "PAID":
        raise err(ERR_DEPENDENCY_NOT_READY, "Payment not settled")
    _complete_fulfillment(order, "PICKED_UP")
    return success(public(order), 200)


def _complete_fulfillment(order, new_status):
    order["fulfillment_status"] = new_status
    lines = [l for l in db.db.order_lines.values() if l["order_id"] == order["id"]]
    for line in lines:
        item = db.db.inventory_items.get(line["inventory_item_id"])
        if item is None:
            continue
        item["status"] = "SOLD"
        touch(item)
        settle_consignment_sale(item, line)
    touch(order)


@bp.route("/shop/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = authenticate({"Customer", "StoreClerk"})
    order = lookup(db.db.orders, oid)
    _owner_check(role, user_id, order["customer_id"])
    if order["fulfillment_status"] in ("SHIPPED", "PICKED_UP", "CANCELLED"):
        raise err(ERR_INVALID_STATE, "Order cannot be cancelled")
    # refund if PAID
    if order["payment_status"] == "PAID":
        customer = db.db.customers[order["customer_id"]]
        customer["store_credit_cents"] += order["credit_applied_cents"]
        customer["loyalty_points"] -= order["points_earned"]
        if customer["loyalty_points"] < 0:
            customer["loyalty_points"] = 0
        recompute_tier(customer)
        touch(customer)
        order["payment_status"] = "REFUNDED"
    # release reserved items
    order["fulfillment_status"] = "CANCELLED"
    lines = [l for l in db.db.order_lines.values() if l["order_id"] == oid]
    for line in lines:
        item = db.db.inventory_items.get(line["inventory_item_id"])
        if item is not None and item["status"] == "RESERVED":
            release_item(item)
    touch(order)
    return success(public(order), 200)
