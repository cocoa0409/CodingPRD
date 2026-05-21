"""Order endpoints — placement and restaurant-side flow.

Dispatch and delivery cascades are wired into the assignment routes and the
dispatch module; this file is the customer-facing entrypoint plus the
restaurant lifecycle transitions.
"""
from __future__ import annotations

from flask import Blueprint, request

from .. import cascade, fees
from ..auth import require_role
from ..dispatch import open_dispatch
from ..envelope import envelope_array, envelope_object, expect_json_body
from ..errors import ApiError
from ..geo import distance_km
from ..ids import new_uuid
from ..pagination import apply as apply_pagination, parse as parse_pagination
from ..peak import is_peak
from ..store import get_clock, get_store
from ..validators import req_int, req_str

bp = Blueprint("orders", __name__, url_prefix="/api")


ORDER_STATUSES = {
    "PLACED", "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
    "PICKED_UP", "DELIVERED", "CANCELLED", "REFUND_REQUESTED", "REFUNDED",
}


def _ensure_order(store, oid):
    rec = store.orders.get(oid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Order {oid} not found")
    return rec


def _can_read_order(uid, role, order, store):
    if role in {"PlatformAdmin", "CustomerService"}:
        return True
    if role == "Customer":
        return uid == order["customer_id"]
    if role == "Restaurant":
        return uid == order["restaurant_id"]
    if role == "Rider":
        # Any assignment for this order with this rider.
        for a in store.assignments.values():
            if a["order_id"] == order["id"] and a["rider_id"] == uid:
                return True
        return False
    return False


@bp.post("/orders")
def place_order():
    uid, _ = require_role({"Customer"})
    body = expect_json_body()

    # Foreign keys first per validation priority
    customer_id = req_str(body, "customer_id")
    restaurant_id = req_str(body, "restaurant_id")
    items = body.get("items")

    store = get_store()
    clock = get_clock()
    with store.lock:
        # Priority 4: FK existence — customer_id, restaurant_id, menu_item_id
        customer = store.customers.get(customer_id)
        if not customer:
            raise ApiError("ERR_NOT_FOUND", "customer_id not found")
        restaurant = store.restaurants.get(restaurant_id)
        if not restaurant:
            raise ApiError("ERR_NOT_FOUND", "restaurant_id not found")
        if not isinstance(items, list):
            # Defer — can't iterate, surface as ORDER_INVALID later.
            items_list_ok = False
        else:
            items_list_ok = True
            for it in items:
                if not isinstance(it, dict):
                    items_list_ok = False
                    break
                mid = it.get("menu_item_id")
                if mid is not None and not isinstance(mid, str):
                    items_list_ok = False
                    break
                if isinstance(mid, str) and mid not in store.menu_items:
                    raise ApiError("ERR_NOT_FOUND", "menu_item_id not found")

        # Priority 5: identity match.
        if uid != customer_id:
            raise ApiError("ERR_FORBIDDEN", "customer_id must match X-User-ID")

        # Priority 7: domain availability checks.
        if restaurant["status"] != "ACTIVE":
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "restaurant not active")
        if items_list_ok:
            for it in items:
                mid = it.get("menu_item_id")
                if mid is None:
                    continue
                mi = store.menu_items[mid]
                if mi["restaurant_id"] != restaurant_id or not mi["is_listed"]:
                    raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "menu item unavailable")

        # Priority 11: shape checks specific to order body.
        if not items_list_ok:
            raise ApiError("ERR_ORDER_INVALID", "items must be a list of item objects")
        if len(items) == 0:
            raise ApiError("ERR_ORDER_INVALID", "items must be non-empty")
        cleaned = []
        subtotal = 0
        for it in items:
            qty = it.get("quantity")
            mid = it.get("menu_item_id")
            if mid is None:
                raise ApiError("ERR_ORDER_INVALID", "menu_item_id required on each item")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                raise ApiError("ERR_ORDER_INVALID", "quantity must be >=1")
            mi = store.menu_items[mid]
            unit_price = mi["price_cents"]
            cleaned.append({
                "menu_item_id": mi["id"],
                "name": mi["name"],
                "unit_price_cents": unit_price,
                "quantity": qty,
            })
            subtotal += unit_price * qty

        if subtotal < 100:
            raise ApiError("ERR_ORDER_INVALID", "subtotal below 100 cents")

        dist = distance_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
        now = clock.now_dt()
        peak = is_peak(now)
        from datetime import timedelta
        promised = now + timedelta(minutes=45)

        provisional_fee = fees.delivery_fee(dist, peak)
        provisional_commission = fees.tiered_commission(subtotal)

        # Payment authorization with credit drawdown
        credit = customer["credit_balance_cents"]
        total_due = subtotal + provisional_fee
        applied_credit = min(credit, total_due)
        customer["credit_balance_cents"] = credit - applied_credit
        if applied_credit > 0:
            cascade.touch(customer, clock)

        from ..clock import iso
        now_iso = iso(now)
        order = {
            "id": new_uuid(),
            "customer_id": customer_id,
            "restaurant_id": restaurant_id,
            "items": cleaned,
            "subtotal_cents": subtotal,
            "distance_km": dist,
            "is_peak": peak,
            "promised_delivery_time": iso(promised),
            "provisional_delivery_fee_cents": provisional_fee,
            "provisional_commission_cents": provisional_commission,
            "final_delivery_fee_cents": None,
            "final_commission_cents": None,
            "actual_delivery_time": None,
            "minutes_late": None,
            "status": "PLACED",
            "payment_status": "AUTHORIZED",
            "credit_applied_cents": applied_credit,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.orders[order["id"]] = order
    return envelope_object(order, status=201)


@bp.get("/orders/<oid>")
def read_order(oid):
    uid, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    store = get_store()
    with store.lock:
        order = _ensure_order(store, oid)
        if not _can_read_order(uid, role, order, store):
            raise ApiError("ERR_FORBIDDEN", "not your order")
        return envelope_object(order)


@bp.get("/orders")
def list_orders():
    uid, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    limit, offset = parse_pagination()
    args = request.args
    customer_q = args.get("customer_id")
    restaurant_q = args.get("restaurant_id")
    rider_q = args.get("rider_id")
    status_q = args.get("status")
    if status_q and status_q not in ORDER_STATUSES:
        raise ApiError("ERR_VALIDATION", "invalid status filter")
    store = get_store()
    with store.lock:
        items = list(store.orders.values())
        # Role scope
        if role == "Customer":
            items = [o for o in items if o["customer_id"] == uid]
        elif role == "Restaurant":
            items = [o for o in items if o["restaurant_id"] == uid]
        elif role == "Rider":
            ridden = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == uid}
            items = [o for o in items if o["id"] in ridden]
        if customer_q:
            items = [o for o in items if o["customer_id"] == customer_q]
        if restaurant_q:
            items = [o for o in items if o["restaurant_id"] == restaurant_q]
        if rider_q:
            ridden = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == rider_q}
            items = [o for o in items if o["id"] in ridden]
        if status_q:
            items = [o for o in items if o["status"] == status_q]
        window, total = apply_pagination(items, limit, offset)
    return envelope_array(window, limit=limit, offset=offset, total_count=total)


@bp.post("/orders/<oid>/accept")
def restaurant_accept(oid):
    uid, _ = require_role({"Restaurant"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if uid != order["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN", "not this restaurant's order")
        if order["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE", "order not PLACED")
        restaurant = store.restaurants[order["restaurant_id"]]
        if restaurant["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "restaurant not ACTIVE")
        order["status"] = "RESTAURANT_ACCEPTED"
        cascade.touch(order, clock)
    return envelope_object(order)


@bp.post("/orders/<oid>/cancel")
def cancel_order_route(oid):
    uid, role = require_role({"Customer", "Restaurant", "CustomerService"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if role == "Customer" and uid != order["customer_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your order")
        if role == "Restaurant" and uid != order["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN", "not this restaurant's order")
        if order["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE", "order not PLACED")
        cascade.cancel_order(store, clock, order)
    return envelope_object(order)


@bp.post("/orders/<oid>/start-preparing")
def start_preparing(oid):
    uid, _ = require_role({"Restaurant"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if uid != order["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your restaurant")
        if order["status"] != "RESTAURANT_ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", "order not RESTAURANT_ACCEPTED")
        order["status"] = "PREPARING"
        cascade.touch(order, clock)
        open_dispatch(store, clock, order)
    return envelope_object(order)


@bp.post("/orders/<oid>/ready")
def mark_ready(oid):
    uid, _ = require_role({"Restaurant"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if uid != order["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your restaurant")
        if order["status"] != "PREPARING":
            raise ApiError("ERR_INVALID_STATE", "order not PREPARING")
        # Rider must have accepted (or be further along)
        has_accept = any(
            a for a in store.assignments.values()
            if a["order_id"] == oid and a["status"] in {"ACCEPTED", "PICKED_UP"}
        )
        if not has_accept:
            raise ApiError("ERR_INVALID_STATE", "no rider has accepted dispatch")
        order["status"] = "READY_FOR_PICKUP"
        cascade.touch(order, clock)
    return envelope_object(order)


@bp.post("/orders/<oid>/dispatch")
def dispatch_order(oid):
    require_role({"PlatformAdmin", "CustomerService"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        order = _ensure_order(store, oid)
        if order["status"] not in {"RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"}:
            raise ApiError("ERR_INVALID_STATE", "order not dispatchable")
        new_assignment = open_dispatch(store, clock, order, force=True)
        if new_assignment is None:
            raise ApiError("ERR_INVALID_STATE", "no eligible rider")
    return envelope_object(new_assignment, status=201)
