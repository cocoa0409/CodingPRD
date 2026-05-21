"""Order placement and restaurant-side lifecycle endpoints."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_list, success_object
from ..errors import ApiError
from ..fees import (
    commission_cents,
    is_peak_at,
    solo_delivery_fee_cents,
    tiered_commission_cents,
)
from ..geo import haversine_km, round_distance_km
from ..ids import new_uuid
from ..pagination import page_slice, parse_pagination
from ..serializers import order_out
from ..validation import ensure_dict, require_int, require_str


bp = Blueprint("orders", __name__, url_prefix="/api")


@bp.post("/orders")
def place_order():
    require_role("Customer")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})

    # 1. Foreign key existence first (validation pipeline step 4).
    customer_id = require_str(body, "customer_id")
    restaurant_id = require_str(body, "restaurant_id")
    items_raw = body.get("items")
    if not isinstance(items_raw, list):
        raise ApiError("ERR_VALIDATION", "items must be a list")

    with store.lock:
        customer = store.customers.get(customer_id)
        if not customer:
            raise ApiError("ERR_NOT_FOUND")
        restaurant = store.restaurants.get(restaurant_id)
        if not restaurant:
            raise ApiError("ERR_NOT_FOUND")
        # Validate every menu_item_id resolves.
        resolved_items = []
        for entry in items_raw:
            if not isinstance(entry, dict):
                raise ApiError("ERR_VALIDATION", "items entries must be objects")
            mid = entry.get("menu_item_id")
            if not isinstance(mid, str) or not mid:
                raise ApiError("ERR_VALIDATION", "items[].menu_item_id required")
            m = store.menu_items.get(mid)
            if not m:
                raise ApiError("ERR_NOT_FOUND")
            resolved_items.append((entry, m))

        # 5. Identity match: a customer can only place for themselves.
        if g.user_id != customer_id:
            raise ApiError("ERR_FORBIDDEN")

        # 7. Domain availability: restaurant ACTIVE and every menu item listed and owned by it.
        if restaurant["status"] != "ACTIVE":
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE")
        for _entry, m in resolved_items:
            if not m["is_listed"] or m["restaurant_id"] != restaurant_id:
                raise ApiError("ERR_RESTAURANT_UNAVAILABLE")

        # 11. Shape-of-input on the order body proper.
        if not resolved_items:
            raise ApiError("ERR_ORDER_INVALID")
        items_out = []
        subtotal = 0
        for entry, m in resolved_items:
            qty_raw = entry.get("quantity")
            if isinstance(qty_raw, bool) or not isinstance(qty_raw, int) or qty_raw < 1:
                raise ApiError("ERR_ORDER_INVALID")
            # Snapshot name and unit_price from current menu item (PRD §3.4).
            name = m["name"]
            unit_price = m["price_cents"]
            items_out.append(
                {
                    "menu_item_id": m["id"],
                    "name": name,
                    "unit_price_cents": unit_price,
                    "quantity": qty_raw,
                }
            )
            subtotal += unit_price * qty_raw
        if subtotal < 100:
            raise ApiError("ERR_ORDER_INVALID")

        # Compute derived fields.
        now_dt = store.clock.now()
        now_iso = store.now_iso()
        dist_raw = haversine_km(
            restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"]
        )
        distance_km = round_distance_km(dist_raw)
        is_peak = is_peak_at(now_dt)
        provisional_fee = solo_delivery_fee_cents(distance_km, is_peak)
        provisional_commission = tiered_commission_cents(subtotal)
        promised = store.clock.now() + timedelta(minutes=45)
        from ..clock import iso_z

        oid = new_uuid()
        o = {
            "id": oid,
            "customer_id": customer_id,
            "restaurant_id": restaurant_id,
            "items": items_out,
            "subtotal_cents": subtotal,
            "distance_km": distance_km,
            "is_peak": is_peak,
            "status": "PLACED",
            "payment_status": "AUTHORIZED",
            "promised_delivery_time": iso_z(promised),
            "actual_delivery_time": None,
            "minutes_late": None,
            "provisional_delivery_fee_cents": provisional_fee,
            "final_delivery_fee_cents": None,
            "provisional_commission_cents": provisional_commission,
            "final_commission_cents": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.orders[oid] = o
        # The PRD's wording: "any available credit_balance_cents is drawn down
        # before the card authorization covers the remaining amount." This is
        # the placement-time draw of credit against the charge. Total charge =
        # subtotal + provisional_delivery_fee (commission is platform-side, not
        # customer-paid). We deduct credit up to that total.
        total_due = subtotal + provisional_fee
        if customer["credit_balance_cents"] > 0:
            applied = min(customer["credit_balance_cents"], total_due)
            customer["credit_balance_cents"] -= applied
            customer["version"] += 1
            customer["updated_at"] = now_iso
        return success_object(store.clock, order_out(o), status=201)


@bp.get("/orders/<oid>")
def read_order(oid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    store = g.store
    o = store.orders.get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND")
    _enforce_order_read(o)
    return success_object(store.clock, order_out(o))


@bp.get("/orders")
def list_orders():
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_pagination()
    store = g.store
    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_q = request.args.get("status")

    rows = list(store.orders.values())
    if customer_id:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if restaurant_id:
        rows = [o for o in rows if o["restaurant_id"] == restaurant_id]
    if status_q:
        rows = [o for o in rows if o["status"] == status_q]
    if rider_id:
        rider_orders = {
            a["order_id"] for a in store.assignments.values() if a["rider_id"] == rider_id
        }
        rows = [o for o in rows if o["id"] in rider_orders]

    # Role-scoped visibility.
    if g.user_role == "Customer":
        rows = [o for o in rows if o["customer_id"] == g.user_id]
    elif g.user_role == "Restaurant":
        rows = [o for o in rows if o["restaurant_id"] == g.user_id]
    elif g.user_role == "Rider":
        rider_orders = {
            a["order_id"] for a in store.assignments.values() if a["rider_id"] == g.user_id
        }
        rows = [o for o in rows if o["id"] in rider_orders]

    page, total = page_slice(rows, limit=limit, offset=offset)
    return success_list(
        store.clock,
        [order_out(o) for o in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


def _enforce_order_read(o: dict) -> None:
    role = g.user_role
    if role == "Customer" and g.user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if role == "Restaurant" and g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN")
    if role == "Rider":
        # Rider may read the order if any of their assignments references it.
        store = g.store
        ok = any(
            a["rider_id"] == g.user_id and a["order_id"] == o["id"]
            for a in store.assignments.values()
        )
        if not ok:
            raise ApiError("ERR_FORBIDDEN")


# --- Restaurant-side transitions -------------------------------------------


@bp.post("/orders/<oid>/accept")
def restaurant_accept(oid: str):
    require_role("Restaurant")
    store = g.store
    with store.lock:
        o = store.orders.get(oid)
        if not o:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != o["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if o["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE")
        r = store.restaurants.get(o["restaurant_id"])
        if not r or r["status"] != "ACTIVE":
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE")
        o["status"] = "RESTAURANT_ACCEPTED"
        o["version"] += 1
        o["updated_at"] = store.now_iso()
        return success_object(store.clock, order_out(o))


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid: str):
    require_role("Customer", "Restaurant", "CustomerService")
    store = g.store
    with store.lock:
        o = store.orders.get(oid)
        if not o:
            raise ApiError("ERR_NOT_FOUND")
        # Identity match for Customer / Restaurant.
        if g.user_role == "Customer" and g.user_id != o["customer_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if g.user_role == "Restaurant" and g.user_id != o["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if o["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE")
        prev_payment = o["payment_status"]
        o["status"] = "CANCELLED"
        if prev_payment in ("UNPAID", "AUTHORIZED"):
            o["payment_status"] = "VOIDED"
        o["version"] += 1
        o["updated_at"] = store.now_iso()
        return success_object(store.clock, order_out(o))


@bp.post("/orders/<oid>/start-preparing")
def start_preparing(oid: str):
    require_role("Restaurant")
    store = g.store
    with store.lock:
        o = store.orders.get(oid)
        if not o:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != o["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if o["status"] != "RESTAURANT_ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
        o["status"] = "PREPARING"
        o["version"] += 1
        o["updated_at"] = store.now_iso()
        # Open a dispatch offer.
        from ..services.dispatch import dispatch_for_order
        dispatch_for_order(store, o)
        return success_object(store.clock, order_out(o))


@bp.post("/orders/<oid>/ready")
def mark_ready(oid: str):
    require_role("Restaurant")
    store = g.store
    with store.lock:
        o = store.orders.get(oid)
        if not o:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != o["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if o["status"] != "PREPARING":
            raise ApiError("ERR_INVALID_STATE")
        # Need an Assignment in ACCEPTED or PICKED_UP for this order.
        has_active = any(
            a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
            for a in store.assignments.values()
        )
        if not has_active:
            raise ApiError("ERR_INVALID_STATE")
        o["status"] = "READY_FOR_PICKUP"
        o["version"] += 1
        o["updated_at"] = store.now_iso()
        return success_object(store.clock, order_out(o))


@bp.post("/orders/<oid>/dispatch")
def dispatch_order(oid: str):
    require_role("PlatformAdmin", "CustomerService")
    store = g.store
    with store.lock:
        o = store.orders.get(oid)
        if not o:
            raise ApiError("ERR_NOT_FOUND")
        # Dispatch is only meaningful for an order in PREPARING / READY_FOR_PICKUP
        # / RESTAURANT_ACCEPTED. (The PRD doesn't gate by status as long as a
        # candidate exists, but we still refuse for terminal states.)
        if o["status"] in ("DELIVERED", "CANCELLED", "REFUNDED", "REFUND_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE")
        if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            raise ApiError("ERR_INVALID_STATE")
        from ..services.dispatch import dispatch_for_order
        new_assignment = dispatch_for_order(store, o)
        if new_assignment is None:
            raise ApiError("ERR_INVALID_STATE", "no available rider in candidate pool")
        from ..serializers import assignment_out
        return success_object(store.clock, assignment_out(new_assignment), status=201)
