"""Order placement, restaurant-side flow, cancellation."""
from flask import request

from ..auth import parse_headers, require_role
from ..clock import format_iso
from ..envelope import success
from ..errors import fail
from ..formulas import (
    haversine_km, is_peak_at, delivery_fee_solo, commission_tiered,
)
from ..pagination import parse_pagination, window
from ..resource import stamp_new, bump
from ..server import store, clock
from datetime import timedelta


def register(app, prefix):
    app.add_url_rule("/api/orders", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/orders", endpoint=f"{prefix}.list", view_func=list_orders, methods=["GET"])
    app.add_url_rule("/api/orders/<oid>/accept", endpoint=f"{prefix}.accept", view_func=accept, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>/cancel", endpoint=f"{prefix}.cancel", view_func=cancel, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>/start-preparing", endpoint=f"{prefix}.start_preparing", view_func=start_preparing, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>/ready", endpoint=f"{prefix}.ready", view_func=ready, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>/dispatch", endpoint=f"{prefix}.dispatch", view_func=dispatch_endpoint, methods=["POST"])
    app.add_url_rule("/api/orders/<oid>/returns", endpoint=f"{prefix}.open_return", view_func=open_return, methods=["POST"])


def _load(oid):
    o = store.orders.get(oid)
    if not o:
        raise fail("ERR_NOT_FOUND")
    return o


def create():
    user_id, role = parse_headers()
    require_role("Customer")
    body = request.get_json(silent=True) or {}
    customer_id = body.get("customer_id")
    restaurant_id = body.get("restaurant_id")
    items = body.get("items")
    if customer_id is None or restaurant_id is None:
        raise fail("ERR_VALIDATION", "customer_id and restaurant_id required")
    customer = store.customers.get(customer_id)
    if not customer:
        raise fail("ERR_NOT_FOUND")
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise fail("ERR_NOT_FOUND")
    if user_id != customer_id:
        raise fail("ERR_FORBIDDEN")

    if not isinstance(items, list) or len(items) == 0:
        raise fail("ERR_ORDER_INVALID", "items must be a non-empty list")
    # Validate menu items exist before unavailability/shape checks
    seen_items = []
    for it in items:
        if not isinstance(it, dict):
            raise fail("ERR_VALIDATION", "each item must be an object")
        mi_id = it.get("menu_item_id")
        if mi_id is None:
            raise fail("ERR_VALIDATION", "menu_item_id required")
        if mi_id not in store.menu_items:
            raise fail("ERR_NOT_FOUND")
        seen_items.append((it, store.menu_items[mi_id]))

    if restaurant["status"] != "ACTIVE":
        raise fail("ERR_RESTAURANT_UNAVAILABLE", "restaurant is not ACTIVE")
    for it, mi in seen_items:
        if mi["restaurant_id"] != restaurant_id or not mi["is_listed"]:
            raise fail("ERR_RESTAURANT_UNAVAILABLE", "menu item unavailable")

    subtotal = 0
    snapshot_items = []
    for it, mi in seen_items:
        qty = it.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise fail("ERR_ORDER_INVALID", "quantity must be int >= 1")
        unit = mi["price_cents"]
        subtotal += unit * qty
        snapshot_items.append({
            "menu_item_id": mi["id"],
            "name": mi["name"],
            "unit_price_cents": unit,
            "quantity": qty,
        })
    if subtotal < 100:
        raise fail("ERR_ORDER_INVALID", "subtotal must be >= 100 cents")

    now = clock.now()
    distance_km = haversine_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    is_peak = is_peak_at(now)
    provisional_delivery = delivery_fee_solo(distance_km, is_peak)
    if restaurant["commission_rate_override"] is not None:
        # Provisional commission still uses the tiered formula per §3.4 — override only matters on delivery.
        # PRD §3.4 says provisional uses tiered. §3.7 says override applies at delivery reconciliation.
        provisional_commission = commission_tiered(subtotal)
    else:
        provisional_commission = commission_tiered(subtotal)

    promised = now + timedelta(minutes=45)
    rec = stamp_new()
    rec.update({
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "items": snapshot_items,
        "subtotal_cents": subtotal,
        "distance_km": distance_km,
        "is_peak": is_peak,
        "promised_delivery_time": format_iso(promised),
        "provisional_delivery_fee_cents": provisional_delivery,
        "provisional_commission_cents": provisional_commission,
        "final_delivery_fee_cents": None,
        "final_commission_cents": None,
        "actual_delivery_time": None,
        "minutes_late": None,
        "status": "PLACED",
        "payment_status": "UNPAID",
    })

    # Payment authorization side-effect: draw down credit, then card-authorize the remainder.
    total_due = subtotal + provisional_delivery
    credit_used = min(customer["credit_balance_cents"], total_due)
    customer["credit_balance_cents"] -= credit_used
    bump(customer)
    rec["credit_used_cents"] = credit_used
    rec["card_authorized_cents"] = total_due - credit_used
    rec["payment_status"] = "AUTHORIZED"

    store.orders[rec["id"]] = rec
    return success(rec, status=201)


def read(oid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    o = _load(oid)
    if role == "Customer" and user_id != o["customer_id"]:
        raise fail("ERR_FORBIDDEN")
    if role == "Restaurant" and user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    if role == "Rider":
        # Rider may read an order only if they hold an active assignment on it
        if not any(a["order_id"] == o["id"] and a["rider_id"] == user_id
                   for a in store.assignments.values()):
            raise fail("ERR_FORBIDDEN")
    return success(o)


def list_orders():
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_filter = request.args.get("status")
    # Role-scoped narrowing
    if role == "Customer":
        if customer_id is not None and customer_id != user_id:
            raise fail("ERR_FORBIDDEN")
        customer_id = user_id
    if role == "Restaurant":
        if restaurant_id is not None and restaurant_id != user_id:
            raise fail("ERR_FORBIDDEN")
        restaurant_id = user_id
    if role == "Rider":
        if rider_id is not None and rider_id != user_id:
            raise fail("ERR_FORBIDDEN")
        rider_id = user_id

    rows = list(store.orders.values())
    if customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if restaurant_id is not None:
        rows = [o for o in rows if o["restaurant_id"] == restaurant_id]
    if rider_id is not None:
        rider_orders = {a["order_id"] for a in store.assignments.values()
                        if a["rider_id"] == rider_id}
        rows = [o for o in rows if o["id"] in rider_orders]
    if status_filter is not None:
        rows = [o for o in rows if o["status"] == status_filter]
    rows.sort(key=lambda o: o["created_at"])
    page, meta = window(rows, limit, offset)
    return success(page, page=meta, response_type="array")


def accept(oid):
    user_id, role = parse_headers()
    require_role("Restaurant")
    o = _load(oid)
    if user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    if o["status"] != "PLACED":
        raise fail("ERR_INVALID_STATE")
    restaurant = store.restaurants.get(o["restaurant_id"])
    if restaurant["status"] != "ACTIVE":
        raise fail("ERR_INVALID_STATE")
    o["status"] = "RESTAURANT_ACCEPTED"
    bump(o)
    return success(o)


def cancel(oid):
    user_id, role = parse_headers()
    require_role("Customer", "Restaurant", "CustomerService")
    o = _load(oid)
    if role == "Customer" and user_id != o["customer_id"]:
        raise fail("ERR_FORBIDDEN")
    if role == "Restaurant" and user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    if o["status"] != "PLACED":
        raise fail("ERR_INVALID_STATE")
    o["status"] = "CANCELLED"
    if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
        o["payment_status"] = "VOIDED"
    # Return any credit drawn down at authorization back to the customer.
    if o.get("credit_used_cents", 0) > 0:
        customer = store.customers.get(o["customer_id"])
        if customer:
            customer["credit_balance_cents"] += o["credit_used_cents"]
            bump(customer)
        o["credit_used_cents"] = 0
    bump(o)
    return success(o)


def start_preparing(oid):
    user_id, role = parse_headers()
    require_role("Restaurant")
    o = _load(oid)
    if user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    if o["status"] != "RESTAURANT_ACCEPTED":
        raise fail("ERR_INVALID_STATE")
    o["status"] = "PREPARING"
    bump(o)
    from ..services.dispatch import dispatch_order
    dispatch_order(o)
    return success(o)


def ready(oid):
    user_id, role = parse_headers()
    require_role("Restaurant")
    o = _load(oid)
    if user_id != o["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    if o["status"] != "PREPARING":
        raise fail("ERR_INVALID_STATE")
    if not any(a["order_id"] == o["id"] and a["status"] in ("ACCEPTED", "PICKED_UP")
               for a in store.assignments.values()):
        raise fail("ERR_INVALID_STATE")
    o["status"] = "READY_FOR_PICKUP"
    bump(o)
    return success(o)


def dispatch_endpoint(oid):
    parse_headers()
    require_role("PlatformAdmin", "CustomerService")
    o = _load(oid)
    if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise fail("ERR_INVALID_STATE")
    from ..services.dispatch import dispatch_order
    assignment = dispatch_order(o)
    return success(assignment, status=201)


def open_return(oid):
    from ..services.refunds import open_return as svc
    return svc(oid)
