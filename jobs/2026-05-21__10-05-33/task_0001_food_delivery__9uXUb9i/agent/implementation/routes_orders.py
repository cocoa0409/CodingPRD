"""Order endpoints — placement, restaurant flow, returns opening."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import require_roles
from common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
    require_str,
    require_int,
    haversine_km,
    round_distance_km,
    is_peak,
)
from envelope import success
from errors import ApiError
from pricing import (
    compute_provisional_delivery_fee,
    compute_provisional_commission,
)
from serializers import serialize_order, serialize_return
import store
from store import gen_id, iso_z, lock, now
from datetime import timedelta


bp = Blueprint("orders", __name__, url_prefix="/api/orders")


def _find_order(oid: str) -> dict:
    o = store.orders.get(oid)
    if not o:
        raise ApiError("ERR_NOT_FOUND", "Order not found.")
    return o


def _check_version(resource: dict, body: dict) -> None:
    if "version" in body and body["version"] is not None:
        if body["version"] != resource["version"]:
            raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


@bp.post("")
@require_roles("Customer")
def place_order():
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    restaurant_id = require_str(body, "restaurant_id")

    # Body FK existence checks (step 4)
    cust = store.customers.get(customer_id)
    if not cust:
        raise ApiError("ERR_NOT_FOUND", "Customer not found.")
    rest = store.restaurants.get(restaurant_id)
    if not rest:
        raise ApiError("ERR_NOT_FOUND", "Restaurant not found.")

    items_raw = body.get("items")
    if not isinstance(items_raw, list):
        raise ApiError("ERR_VALIDATION", "items must be an array.")

    # FK validation for each menu_item_id
    for entry in items_raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", "each items entry must be an object.")
        mid = entry.get("menu_item_id")
        if not isinstance(mid, str):
            raise ApiError("ERR_VALIDATION", "menu_item_id must be a string.")
        if mid not in store.menu_items:
            raise ApiError("ERR_NOT_FOUND", "Menu item not found.")

    # Identity match: X-User-ID == customer_id
    if g.user_id != customer_id:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")

    # Domain: restaurant must be ACTIVE; items must be listed and belong to restaurant
    if rest["status"] != "ACTIVE":
        raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "Restaurant is not active.")
    for entry in items_raw:
        mi = store.menu_items[entry["menu_item_id"]]
        if not mi["is_listed"]:
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "Menu item is not listed.")
        if mi["restaurant_id"] != restaurant_id:
            raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "Menu item belongs to a different restaurant.")

    # Shape: items must be non-empty, quantity >= 1
    if len(items_raw) == 0:
        raise ApiError("ERR_ORDER_INVALID", "items must be non-empty.")
    snapshot_items = []
    subtotal = 0
    for entry in items_raw:
        mi = store.menu_items[entry["menu_item_id"]]
        qty = entry.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise ApiError("ERR_VALIDATION", "quantity must be an integer.")
        if qty < 1:
            raise ApiError("ERR_ORDER_INVALID", "quantity must be >= 1.")
        snap = {
            "menu_item_id": mi["id"],
            "name": mi["name"],
            "unit_price_cents": mi["price_cents"],
            "quantity": qty,
        }
        snapshot_items.append(snap)
        subtotal += mi["price_cents"] * qty
    if subtotal < 100:
        raise ApiError("ERR_ORDER_INVALID", "subtotal must be >= 100 cents.")

    t = now()
    dist_km = round_distance_km(haversine_km(rest["lat"], rest["lng"], cust["lat"], cust["lng"]))
    peak = is_peak(t)
    promised = t + timedelta(minutes=45)

    provisional_fee = compute_provisional_delivery_fee(dist_km, peak)
    provisional_commission = compute_provisional_commission(subtotal)

    # Payment authorization: draw down credit balance first
    with lock():
        oid = gen_id()
        order = {
            "id": oid,
            "customer_id": cust["id"],
            "restaurant_id": rest["id"],
            "items": snapshot_items,
            "subtotal_cents": subtotal,
            "distance_km": dist_km,
            "is_peak": peak,
            "promised_delivery_time": iso_z(promised),
            "provisional_delivery_fee_cents": provisional_fee,
            "final_delivery_fee_cents": None,
            "provisional_commission_cents": provisional_commission,
            "final_commission_cents": None,
            "payment_status": "AUTHORIZED",
            "actual_delivery_time": None,
            "minutes_late": None,
            "status": "PLACED",
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.orders[oid] = order
    return success(serialize_order(order), status=201)


@bp.get("/<oid>")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def read_order(oid: str):
    o = _find_order(oid)
    # Identity check
    if g.role == "Customer" and g.user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    if g.role == "Restaurant" and g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    if g.role == "Rider":
        # Rider may read orders for which they hold an assignment
        owns = any(
            a["order_id"] == o["id"] and a["rider_id"] == g.user_id
            for a in store.assignments.values()
        )
        if not owns:
            raise ApiError("ERR_FORBIDDEN", "Rider is not associated with this order.")
    return success(serialize_order(o))


@bp.get("")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_orders():
    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_f = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(store.orders.values())

    if g.role == "Customer":
        items = [o for o in items if o["customer_id"] == g.user_id]
    elif g.role == "Restaurant":
        items = [o for o in items if o["restaurant_id"] == g.user_id]
    elif g.role == "Rider":
        rider_orders = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == g.user_id}
        items = [o for o in items if o["id"] in rider_orders]

    if customer_id:
        items = [o for o in items if o["customer_id"] == customer_id]
    if restaurant_id:
        items = [o for o in items if o["restaurant_id"] == restaurant_id]
    if rider_id:
        rider_orders = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == rider_id}
        items = [o for o in items if o["id"] in rider_orders]
    if status_f:
        items = [o for o in items if o["status"] == status_f]
    items.sort(key=lambda o: o["created_at"])
    window, meta = paginate(items, limit, offset)
    return success([serialize_order(o) for o in window], list_meta=meta)


@bp.post("/<oid>/accept")
@require_roles("Restaurant")
def accept_order(oid: str):
    o = _find_order(oid)
    if g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    if o["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", "Order is not in PLACED state.")
    rest = store.restaurants[o["restaurant_id"]]
    if rest["status"] != "ACTIVE":
        raise ApiError("ERR_RESTAURANT_UNAVAILABLE", "Restaurant is not active.")
    with lock():
        o["status"] = "RESTAURANT_ACCEPTED"
        o["updated_at"] = iso_z(now())
        o["version"] += 1
    return success(serialize_order(o))


@bp.post("/<oid>/cancel")
@require_roles("Customer", "Restaurant", "CustomerService")
def cancel_order(oid: str):
    o = _find_order(oid)
    if g.role == "Customer" and g.user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    if g.role == "Restaurant" and g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    if o["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", "Order can only be cancelled while in PLACED.")
    with lock():
        o["status"] = "CANCELLED"
        if o["payment_status"] in ("AUTHORIZED", "UNPAID"):
            o["payment_status"] = "VOIDED"
        o["updated_at"] = iso_z(now())
        o["version"] += 1
    return success(serialize_order(o))


@bp.post("/<oid>/start-preparing")
@require_roles("Restaurant")
def start_preparing(oid: str):
    o = _find_order(oid)
    if g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    if o["status"] != "RESTAURANT_ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Order must be RESTAURANT_ACCEPTED to start preparing.")
    with lock():
        o["status"] = "PREPARING"
        o["updated_at"] = iso_z(now())
        o["version"] += 1
        # Open a dispatch offer to the best available rider
        from dispatch import open_dispatch_offer
        open_dispatch_offer(o)
    return success(serialize_order(o))


@bp.post("/<oid>/ready")
@require_roles("Restaurant")
def mark_ready(oid: str):
    o = _find_order(oid)
    if g.user_id != o["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    if o["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", "Order must be in PREPARING.")
    # A rider must have ACCEPTED or PICKED_UP an assignment for this order
    rider_ready = any(
        a["order_id"] == o["id"] and a["status"] in ("ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    if not rider_ready:
        raise ApiError("ERR_INVALID_STATE", "No rider has accepted this dispatch yet.")
    with lock():
        o["status"] = "READY_FOR_PICKUP"
        o["updated_at"] = iso_z(now())
        o["version"] += 1
    return success(serialize_order(o))


@bp.post("/<oid>/dispatch")
@require_roles("PlatformAdmin", "CustomerService")
def dispatch_order(oid: str):
    o = _find_order(oid)
    # Re-dispatch creates a fresh OFFERED Assignment as long as the candidate
    # pool is non-empty.
    if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise ApiError("ERR_INVALID_STATE", "Order is not in a dispatchable state.")
    with lock():
        from dispatch import open_dispatch_offer
        assignment = open_dispatch_offer(o, raise_on_empty=True)
    from serializers import serialize_assignment
    return success(serialize_assignment(assignment), status=201)


@bp.post("/<oid>/returns")
@require_roles("Customer")
def open_return(oid: str):
    o = _find_order(oid)
    if g.user_id != o["customer_id"]:
        raise ApiError("ERR_FORBIDDEN", "Customer identity mismatch.")
    # Duplicate-return check is explicit in PRD §3.9 — surface
    # ERR_DUPLICATE_RETURN even when the order has been moved to
    # REFUND_REQUESTED by the prior return.
    for r in store.returns_.values():
        if r["order_id"] == o["id"] and r["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            raise ApiError("ERR_DUPLICATE_RETURN", "An active return already exists for this order.")
    if o["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "Returns are only available on DELIVERED orders.")
    body = get_json_body()
    reason = require_str(body, "reason")
    if reason not in ("QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"):
        raise ApiError("ERR_VALIDATION", "Invalid return reason.")
    requested_amt = require_int(body, "requested_refund_cents")
    # Temporal window (step 9): 24h from actual_delivery_time
    from datetime import datetime
    from store import iso_z as _iso, now as _now
    actual_dt = _parse_iso(o["actual_delivery_time"])
    if (_now() - actual_dt).total_seconds() > 24 * 3600:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED", "Return window has expired.")
    # Fiscal amount range (step 10)
    if requested_amt < 1 or requested_amt > o["subtotal_cents"]:
        raise ApiError("ERR_REFUND_AMOUNT_INVALID", "requested_refund_cents out of range.")

    with lock():
        t = now()
        rid = gen_id()
        rec = {
            "id": rid,
            "order_id": o["id"],
            "reason": reason,
            "requested_refund_cents": requested_amt,
            "approved_refund_cents": None,
            "reviewer_cs_user_id": None,
            "status": "REQUESTED",
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.returns_[rid] = rec
        # Cascade: order moves to REFUND_REQUESTED
        o["status"] = "REFUND_REQUESTED"
        o["updated_at"] = iso_z(t)
        o["version"] += 1
    return success(serialize_return(rec), status=201)


def _parse_iso(s: str):
    """Parse an ISO 8601 string with Z suffix back to a UTC datetime."""
    from datetime import datetime
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
