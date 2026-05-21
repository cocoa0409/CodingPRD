from datetime import timedelta
from flask import Blueprint, request

from ..auth import require_role
from ..envelope import success, created, list_ok
from ..errors import err
from ..pagination import parse_limit_offset, paginate
from ..repository import base_versioned, touch, check_version, body_or_empty, now_iso
from ..store import store
from ..clock import is_peak, iso
from ..geo import haversine_km, round_distance_km
from ..domain.pricing import (
    solo_delivery_fee_cents,
    tiered_commission_cents,
    commission_cents,
)

bp = Blueprint("orders", __name__)


def _view(o):
    keys = (
        "id", "customer_id", "restaurant_id", "items",
        "subtotal_cents", "distance_km", "is_peak",
        "promised_delivery_time", "actual_delivery_time", "minutes_late",
        "provisional_delivery_fee_cents", "final_delivery_fee_cents",
        "provisional_commission_cents", "final_commission_cents",
        "status", "payment_status",
        "created_at", "updated_at", "version",
    )
    return {k: o.get(k) for k in keys}


@bp.post("/api/orders")
def place_order():
    uid, role = require_role("Customer")
    body = body_or_empty()
    customer_id = body.get("customer_id")
    restaurant_id = body.get("restaurant_id")
    items = body.get("items")

    # FK existence
    if not isinstance(customer_id, str) or customer_id not in store.customers:
        raise err("ERR_NOT_FOUND", "customer not found")
    if not isinstance(restaurant_id, str) or restaurant_id not in store.restaurants:
        raise err("ERR_NOT_FOUND", "restaurant not found")
    if not isinstance(items, list):
        raise err("ERR_ORDER_INVALID", "items must be array")
    if len(items) == 0:
        raise err("ERR_ORDER_INVALID", "items must be non-empty")
    for it in items:
        if not isinstance(it, dict):
            raise err("ERR_VALIDATION", "item must be object")
        mid = it.get("menu_item_id")
        if not isinstance(mid, str) or mid not in store.menu_items:
            raise err("ERR_NOT_FOUND", "menu item not found")

    # Identity match
    if customer_id != uid:
        raise err("ERR_FORBIDDEN", "customer_id must match X-User-ID")

    # Domain availability
    restaurant = store.restaurants[restaurant_id]
    if restaurant["status"] != "ACTIVE":
        raise err("ERR_RESTAURANT_UNAVAILABLE", "restaurant not ACTIVE")
    for it in items:
        m = store.menu_items[it["menu_item_id"]]
        if not m["is_listed"]:
            raise err("ERR_RESTAURANT_UNAVAILABLE", "menu item not listed")
        if m["restaurant_id"] != restaurant_id:
            raise err("ERR_RESTAURANT_UNAVAILABLE", "menu item not in this restaurant")

    # Quantity shape & subtotal
    snapshot_items = []
    subtotal = 0
    for it in items:
        q = it.get("quantity")
        if not isinstance(q, int) or isinstance(q, bool) or q < 1:
            raise err("ERR_ORDER_INVALID", "quantity must be >= 1")
        m = store.menu_items[it["menu_item_id"]]
        snapshot_items.append({
            "menu_item_id": m["id"],
            "name": m["name"],
            "unit_price_cents": m["price_cents"],
            "quantity": q,
        })
        subtotal += m["price_cents"] * q
    if subtotal < 100:
        raise err("ERR_ORDER_INVALID", "subtotal below minimum")

    customer = store.customers[customer_id]
    distance_km = round_distance_km(
        haversine_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    )
    from ..app import logical_clock
    now_dt = logical_clock.now()
    peak = is_peak(now_dt)
    promised = now_dt + timedelta(minutes=45)

    provisional_fee = solo_delivery_fee_cents(distance_km, peak)
    provisional_commission = tiered_commission_cents(subtotal)

    o = base_versioned()
    o.update({
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "items": snapshot_items,
        "subtotal_cents": subtotal,
        "distance_km": distance_km,
        "is_peak": peak,
        "promised_delivery_time": iso(promised),
        "actual_delivery_time": None,
        "minutes_late": None,
        "provisional_delivery_fee_cents": provisional_fee,
        "final_delivery_fee_cents": None,
        "provisional_commission_cents": provisional_commission,
        "final_commission_cents": None,
        "status": "PLACED",
        "payment_status": "AUTHORIZED",
    })
    # Authorize payment: draw down credit then card auth
    total_charge = subtotal + provisional_fee
    credit = min(customer["credit_balance_cents"], total_charge)
    if credit > 0:
        customer["credit_balance_cents"] -= credit
        touch(customer)
    store.orders[o["id"]] = o
    return created(_view(o))


@bp.get("/api/orders/<oid>")
def get_order(oid):
    uid, role = require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if role == "Customer" and o["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if role == "Restaurant" and o["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if role == "Rider":
        # Rider can read if assigned
        ok = any(a["order_id"] == oid and a["rider_id"] == uid
                 and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP", "DELIVERED")
                 for a in store.assignments.values())
        if not ok:
            raise err("ERR_FORBIDDEN", "not your assignment")
    return success(_view(o))


@bp.get("/api/orders")
def list_orders():
    uid, role = require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_limit_offset()
    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_filter = request.args.get("status")
    items = list(store.orders.values())
    if customer_id:
        items = [o for o in items if o["customer_id"] == customer_id]
    if restaurant_id:
        items = [o for o in items if o["restaurant_id"] == restaurant_id]
    if rider_id:
        oid_set = {a["order_id"] for a in store.assignments.values()
                   if a["rider_id"] == rider_id and a["status"] != "REJECTED"}
        items = [o for o in items if o["id"] in oid_set]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]

    # Role-based scoping
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == uid]
    elif role == "Restaurant":
        items = [o for o in items if o["restaurant_id"] == uid]
    elif role == "Rider":
        oid_set = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == uid}
        items = [o for o in items if o["id"] in oid_set]

    items.sort(key=lambda x: x["created_at"])
    window, total = paginate(items, limit, offset)
    return list_ok([_view(x) for x in window], limit, offset, total)


@bp.post("/api/orders/<oid>/accept")
def accept_order(oid):
    uid, role = require_role("Restaurant")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if o["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    restaurant = store.restaurants[o["restaurant_id"]]
    if o["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "order not in PLACED")
    if restaurant["status"] != "ACTIVE":
        raise err("ERR_RESTAURANT_UNAVAILABLE", "restaurant not ACTIVE")
    body = body_or_empty()
    check_version(o, body)
    o["status"] = "RESTAURANT_ACCEPTED"
    touch(o)
    return success(_view(o))


@bp.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = require_role("Customer", "Restaurant", "CustomerService")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if role == "Customer" and o["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if role == "Restaurant" and o["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if o["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "order not in PLACED")
    body = body_or_empty()
    check_version(o, body)
    o["status"] = "CANCELLED"
    if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
        o["payment_status"] = "VOIDED"
    touch(o)
    return success(_view(o))


@bp.post("/api/orders/<oid>/start-preparing")
def start_preparing(oid):
    uid, role = require_role("Restaurant")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if o["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if o["status"] != "RESTAURANT_ACCEPTED":
        raise err("ERR_INVALID_STATE", "not in RESTAURANT_ACCEPTED")
    body = body_or_empty()
    check_version(o, body)
    o["status"] = "PREPARING"
    touch(o)
    # Open dispatch
    from ..domain.dispatch import dispatch_offer
    dispatch_offer(o)
    return success(_view(o))


@bp.post("/api/orders/<oid>/ready")
def ready_order(oid):
    uid, role = require_role("Restaurant")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if o["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your order")
    if o["status"] != "PREPARING":
        raise err("ERR_INVALID_STATE", "not in PREPARING")
    # Must have a rider ACCEPTED or PICKED_UP
    has_accepted = any(a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
                       for a in store.assignments.values())
    if not has_accepted:
        raise err("ERR_INVALID_STATE", "no rider has accepted yet")
    body = body_or_empty()
    check_version(o, body)
    o["status"] = "READY_FOR_PICKUP"
    touch(o)
    return success(_view(o))


@bp.post("/api/orders/<oid>/dispatch")
def dispatch_endpoint(oid):
    require_role("PlatformAdmin", "CustomerService")
    o = store.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise err("ERR_INVALID_STATE", "order state does not accept dispatch")
    from ..domain.dispatch import dispatch_offer
    assignment = dispatch_offer(o)
    if assignment is None:
        raise err("ERR_INVALID_STATE", "no eligible rider available")
    from .assignments import _view as assignment_view
    return created(assignment_view(assignment))
