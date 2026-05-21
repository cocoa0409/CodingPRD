"""Order endpoints."""

from __future__ import annotations

import math
from datetime import timedelta

from flask import request

from auth import require_role
from clock import CLOCK, iso_ms
from dispatch_engine import open_dispatch
from envelope import list_success, success
from errors import APIError
from geo import haversine_km, round_distance_km
from pricing import solo_delivery_fee_cents, tiered_commission_cents
from resources import make_versioned, touch
from store import STORE
from validation import get_body, parse_pagination

VALID_ORDER_STATUSES = {
    "PLACED", "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
    "PICKED_UP", "DELIVERED", "CANCELLED", "REFUND_REQUESTED", "REFUNDED",
}


def _serialize(o: dict) -> dict:
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "restaurant_id": o["restaurant_id"],
        "items": o["items"],
        "subtotal_cents": o["subtotal_cents"],
        "distance_km": o["distance_km"],
        "is_peak": o["is_peak"],
        "promised_delivery_time": o["promised_delivery_time"],
        "actual_delivery_time": o.get("actual_delivery_time"),
        "minutes_late": o.get("minutes_late"),
        "provisional_delivery_fee_cents": o["provisional_delivery_fee_cents"],
        "final_delivery_fee_cents": o.get("final_delivery_fee_cents"),
        "provisional_commission_cents": o["provisional_commission_cents"],
        "final_commission_cents": o.get("final_commission_cents"),
        "status": o["status"],
        "payment_status": o["payment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _is_peak(now) -> bool:
    h = now.hour
    return (11 <= h < 13) or (18 <= h < 20)


def _live_assignment_for_order(order_id: str) -> dict | None:
    for a in STORE.assignments.values():
        if a["order_id"] == order_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return a
    return None


def register(app):
    @app.post("/api/orders")
    def place_order():
        user_id, _ = require_role({"Customer"})
        body = get_body()

        # FK existence: customer_id, restaurant_id, each menu_item_id.
        customer_id = body.get("customer_id")
        restaurant_id = body.get("restaurant_id")
        items_in = body.get("items")
        if not isinstance(customer_id, str):
            raise APIError("ERR_VALIDATION", "customer_id required.")
        if not isinstance(restaurant_id, str):
            raise APIError("ERR_VALIDATION", "restaurant_id required.")

        with STORE.lock:
            customer = STORE.customers.get(customer_id)
            if customer is None:
                raise APIError("ERR_NOT_FOUND", "No such customer.")
            restaurant = STORE.restaurants.get(restaurant_id)
            if restaurant is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")

            if not isinstance(items_in, list):
                raise APIError("ERR_VALIDATION", "items must be a list.")
            # FK existence checks on every menu_item_id (priority 4 — before ownership and state).
            for it in items_in:
                if not isinstance(it, dict):
                    raise APIError("ERR_VALIDATION", "each item must be an object.")
                mid = it.get("menu_item_id")
                if not isinstance(mid, str):
                    raise APIError("ERR_VALIDATION", "items[].menu_item_id required.")
                if mid not in STORE.menu_items:
                    raise APIError("ERR_NOT_FOUND", "No such menu item.")

            # Identity match (priority 5).
            if user_id != customer_id:
                raise APIError("ERR_FORBIDDEN")

            # Domain checks: restaurant must be ACTIVE; items must belong & be listed (priority 7).
            if restaurant["status"] != "ACTIVE":
                raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Restaurant is not ACTIVE.")
            for it in items_in:
                m = STORE.menu_items[it["menu_item_id"]]
                if m["restaurant_id"] != restaurant_id or not m["is_listed"]:
                    raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Menu item is unavailable.")

            # Shape-of-input checks (priority 11).
            if not items_in:
                raise APIError("ERR_ORDER_INVALID", "items must be non-empty.")
            snapshot_items = []
            subtotal = 0
            for it in items_in:
                mid = it["menu_item_id"]
                m = STORE.menu_items[mid]
                qty = it.get("quantity")
                if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
                    raise APIError("ERR_ORDER_INVALID", "quantity must be >= 1.")
                # snapshot name + price from menu item
                unit = m["price_cents"]
                snapshot_items.append({
                    "menu_item_id": mid,
                    "name": m["name"],
                    "unit_price_cents": unit,
                    "quantity": qty,
                })
                subtotal += unit * qty
            if subtotal < 100:
                raise APIError("ERR_ORDER_INVALID", "subtotal must be at least 100 cents.")

            now = CLOCK.now()
            distance_km = round_distance_km(haversine_km(
                restaurant["lat"], restaurant["lng"],
                customer["lat"], customer["lng"],
            ))
            is_peak = _is_peak(now)
            promised = iso_ms(now + timedelta(minutes=45))
            provisional_fee = solo_delivery_fee_cents(distance_km, is_peak)
            provisional_commission = tiered_commission_cents(subtotal)

            # Authorize payment: draw down credit before card.
            order = make_versioned({
                "customer_id": customer_id,
                "restaurant_id": restaurant_id,
                "items": snapshot_items,
                "subtotal_cents": subtotal,
                "distance_km": distance_km,
                "is_peak": is_peak,
                "promised_delivery_time": promised,
                "actual_delivery_time": None,
                "minutes_late": None,
                "provisional_delivery_fee_cents": provisional_fee,
                "final_delivery_fee_cents": None,
                "provisional_commission_cents": provisional_commission,
                "final_commission_cents": None,
                "status": "PLACED",
                "payment_status": "UNPAID",
            })
            order["payment_status"] = "AUTHORIZED"
            STORE.orders[order["id"]] = order
            return success(_serialize(order), status=201)

    @app.get("/api/orders/<oid>")
    def read_order(oid: str):
        user_id, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if role == "Customer" and user_id != o["customer_id"]:
                raise APIError("ERR_FORBIDDEN")
            if role == "Restaurant" and user_id != o["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            if role == "Rider":
                # Rider can read only orders for which they have/had an assignment.
                touched = False
                for a in STORE.assignments.values():
                    if a["order_id"] == o["id"] and a["rider_id"] == user_id:
                        touched = True
                        break
                if not touched:
                    raise APIError("ERR_FORBIDDEN")
            return success(_serialize(o))

    @app.get("/api/orders")
    def list_orders():
        user_id, role = require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
        limit, offset = parse_pagination()
        customer_id = request.args.get("customer_id")
        restaurant_id = request.args.get("restaurant_id")
        rider_id = request.args.get("rider_id")
        status_q = request.args.get("status")
        if status_q is not None and status_q not in VALID_ORDER_STATUSES:
            raise APIError("ERR_VALIDATION", "Invalid status filter.")
        with STORE.lock:
            items = list(STORE.orders.values())
            if role == "Customer":
                items = [o for o in items if o["customer_id"] == user_id]
            elif role == "Restaurant":
                items = [o for o in items if o["restaurant_id"] == user_id]
            elif role == "Rider":
                rider_orders = {a["order_id"] for a in STORE.assignments.values() if a["rider_id"] == user_id}
                items = [o for o in items if o["id"] in rider_orders]
            if customer_id:
                items = [o for o in items if o["customer_id"] == customer_id]
            if restaurant_id:
                items = [o for o in items if o["restaurant_id"] == restaurant_id]
            if rider_id:
                allowed_orders = {a["order_id"] for a in STORE.assignments.values() if a["rider_id"] == rider_id}
                items = [o for o in items if o["id"] in allowed_orders]
            if status_q:
                items = [o for o in items if o["status"] == status_q]
            items.sort(key=lambda o: o["created_at"])
            page = items[offset:offset + limit]
            return list_success([_serialize(o) for o in page], limit, offset, len(items))

    @app.post("/api/orders/<oid>/accept")
    def accept_order(oid: str):
        user_id, _ = require_role({"Restaurant"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if user_id != o["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            if o["status"] != "PLACED":
                raise APIError("ERR_INVALID_STATE", "Order is not in PLACED.")
            r = STORE.restaurants[o["restaurant_id"]]
            if r["status"] != "ACTIVE":
                raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Restaurant must be ACTIVE.")
            o["status"] = "RESTAURANT_ACCEPTED"
            touch(o)
            return success(_serialize(o))

    @app.post("/api/orders/<oid>/cancel")
    def cancel_order(oid: str):
        user_id, role = require_role({"Customer", "Restaurant", "CustomerService"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if role == "Customer" and user_id != o["customer_id"]:
                raise APIError("ERR_FORBIDDEN")
            if role == "Restaurant" and user_id != o["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            if o["status"] != "PLACED":
                raise APIError("ERR_INVALID_STATE", "Only PLACED orders can be cancelled.")
            o["status"] = "CANCELLED"
            if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
                o["payment_status"] = "VOIDED"
            touch(o)
            return success(_serialize(o))

    @app.post("/api/orders/<oid>/start-preparing")
    def start_preparing(oid: str):
        user_id, _ = require_role({"Restaurant"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if user_id != o["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            if o["status"] != "RESTAURANT_ACCEPTED":
                raise APIError("ERR_INVALID_STATE", "Order is not in RESTAURANT_ACCEPTED.")
            o["status"] = "PREPARING"
            touch(o)
            # Open a dispatch offer.
            open_dispatch(o)
            return success(_serialize(o))

    @app.post("/api/orders/<oid>/ready")
    def mark_ready(oid: str):
        user_id, _ = require_role({"Restaurant"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if user_id != o["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            if o["status"] != "PREPARING":
                raise APIError("ERR_INVALID_STATE", "Order is not in PREPARING.")
            has_accepted = any(
                a["order_id"] == o["id"] and a["status"] in ("ACCEPTED", "PICKED_UP")
                for a in STORE.assignments.values()
            )
            if not has_accepted:
                raise APIError("ERR_INVALID_STATE", "No accepted assignment yet.")
            o["status"] = "READY_FOR_PICKUP"
            touch(o)
            return success(_serialize(o))

    @app.post("/api/orders/<oid>/dispatch")
    def dispatch(oid: str):
        require_role({"PlatformAdmin", "CustomerService"})
        with STORE.lock:
            o = STORE.orders.get(oid)
            if o is None:
                raise APIError("ERR_NOT_FOUND", "No such order.")
            if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
                raise APIError("ERR_INVALID_STATE", "Order is not in a dispatchable state.")
            from dispatch_engine import force_dispatch
            assignment = force_dispatch(o)
            from routes_assignments import serialize_assignment
            return success(serialize_assignment(assignment), status=201)
