"""Order endpoints: placement, listing, restaurant flow, dispatch trigger."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import orders as svc
from services import dispatch as dispatch_svc
from services import returns_ as returns_svc


bp = Blueprint("orders", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


@bp.route("/api/orders", methods=["POST"])
def place_order():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Customer":
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    # Body shape (generic) → ERR_VALIDATION
    if "customer_id" not in payload or not isinstance(payload["customer_id"], str):
        return envelope.validation("customer_id must be a string.")
    if "restaurant_id" not in payload or not isinstance(payload["restaurant_id"], str):
        return envelope.validation("restaurant_id must be a string.")
    if "items" not in payload or not isinstance(payload["items"], list):
        return envelope.validation("items must be an array.")

    # Each item must at minimum have menu_item_id (string) and quantity (int).
    for item in payload["items"]:
        if not isinstance(item, dict):
            return envelope.validation("Each item must be an object.")
        if "menu_item_id" not in item or not isinstance(item["menu_item_id"], str):
            return envelope.validation("item.menu_item_id must be a string.")
        if "quantity" not in item or not validators.is_int(item["quantity"]):
            return envelope.validation("item.quantity must be an integer.")

    with state.lock():
        # FK existence
        customer = state.STORE.customers.get(payload["customer_id"])
        if customer is None:
            return envelope.not_found("customer_id not found.")
        restaurant = state.STORE.restaurants.get(payload["restaurant_id"])
        if restaurant is None:
            return envelope.not_found("restaurant_id not found.")
        menu_items = []
        for item in payload["items"]:
            mi = state.STORE.menu_items.get(item["menu_item_id"])
            if mi is None:
                return envelope.not_found(
                    f"menu_item_id {item['menu_item_id']} not found."
                )
            menu_items.append((item, mi))

        # Identity match
        if user_id != customer["id"]:
            return envelope.forbidden()

        # Domain checks
        if restaurant["status"] != "ACTIVE":
            return envelope.error(
                422, "ERR_RESTAURANT_UNAVAILABLE",
                "Restaurant is not ACTIVE.",
            )
        for _, mi in menu_items:
            if not mi["is_listed"]:
                return envelope.error(
                    422, "ERR_RESTAURANT_UNAVAILABLE",
                    "Menu item is not listed.",
                )
            if mi["restaurant_id"] != restaurant["id"]:
                return envelope.error(
                    422, "ERR_RESTAURANT_UNAVAILABLE",
                    "Menu item does not belong to this restaurant.",
                )

        # Order-shape checks
        if not menu_items:
            return envelope.error(
                422, "ERR_ORDER_INVALID", "items must be non-empty."
            )
        for item, _ in menu_items:
            if item["quantity"] < 1:
                return envelope.error(
                    422, "ERR_ORDER_INVALID", "quantity must be >= 1."
                )
        # Snapshot the items from the menu at placement.
        snapped = []
        for item, mi in menu_items:
            snapped.append({
                "menu_item_id": mi["id"],
                "name": mi["name"],
                "unit_price_cents": mi["price_cents"],
                "quantity": item["quantity"],
            })
        subtotal = sum(s["unit_price_cents"] * s["quantity"] for s in snapped)
        if subtotal < 100:
            return envelope.error(
                422, "ERR_ORDER_INVALID",
                "Subtotal must be at least 100 cents.",
            )

        # Place the order. Credit is not drawn at AUTHORIZED — see §3.5.
        order = svc.new_order(customer, restaurant, snapped)
        return envelope.created(projection.render(order))


@bp.route("/api/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    allowed = {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}
    if role not in allowed:
        return envelope.forbidden()

    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if role == "Customer" and user_id != order["customer_id"]:
            return envelope.forbidden()
        if role == "Restaurant" and user_id != order["restaurant_id"]:
            return envelope.forbidden()
        if role == "Rider":
            # Rider can read an order they're assigned to.
            has = any(
                a["order_id"] == oid and a["rider_id"] == user_id
                for a in state.STORE.assignments.values()
            )
            if not has:
                return envelope.forbidden()
        return envelope.success(projection.render(order))


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    allowed = {"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"}
    if role not in allowed:
        return envelope.forbidden()

    page, perr = validators.pagination_params(request.args)
    if perr:
        return perr
    limit, offset = page

    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_filter = request.args.get("status")

    with state.lock():
        orders = list(state.STORE.orders.values())
        if customer_id:
            orders = [o for o in orders if o["customer_id"] == customer_id]
        if restaurant_id:
            orders = [o for o in orders if o["restaurant_id"] == restaurant_id]
        if rider_id:
            assigned_ids = {
                a["order_id"] for a in state.STORE.assignments.values()
                if a["rider_id"] == rider_id
            }
            orders = [o for o in orders if o["id"] in assigned_ids]
        if status_filter:
            orders = [o for o in orders if o["status"] == status_filter]

        # Role-scoped visibility
        if role == "Customer":
            orders = [o for o in orders if o["customer_id"] == user_id]
        elif role == "Restaurant":
            orders = [o for o in orders if o["restaurant_id"] == user_id]
        elif role == "Rider":
            assigned = {
                a["order_id"] for a in state.STORE.assignments.values()
                if a["rider_id"] == user_id
            }
            orders = [o for o in orders if o["id"] in assigned]

        orders.sort(key=lambda o: o["created_at"])
        total = len(orders)
        window = orders[offset : offset + limit]
        return envelope.list_response(
            [projection.render(o) for o in window], limit, offset, total
        )


# --- Restaurant-side flow ---

@bp.route("/api/orders/<oid>/accept", methods=["POST"])
def accept_order(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Restaurant":
        return envelope.forbidden()
    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if user_id != order["restaurant_id"]:
            return envelope.forbidden()
        if order["status"] != "PLACED":
            return envelope.invalid_state(
                "Order must be PLACED to accept."
            )
        restaurant = state.STORE.restaurants[order["restaurant_id"]]
        if restaurant["status"] != "ACTIVE":
            return envelope.invalid_state(
                "Restaurant is not ACTIVE; cannot accept."
            )
        order["status"] = "RESTAURANT_ACCEPTED"
        svc.bump(order)
        return envelope.success(projection.render(order))


@bp.route("/api/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("Customer", "Restaurant", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if role == "Customer" and user_id != order["customer_id"]:
            return envelope.forbidden()
        if role == "Restaurant" and user_id != order["restaurant_id"]:
            return envelope.forbidden()
        if order["status"] != "PLACED":
            return envelope.invalid_state(
                "Order can only be cancelled while PLACED."
            )
        order["status"] = "CANCELLED"
        if order["payment_status"] in ("UNPAID", "AUTHORIZED"):
            order["payment_status"] = "VOIDED"
        svc.bump(order)
        return envelope.success(projection.render(order))


@bp.route("/api/orders/<oid>/start-preparing", methods=["POST"])
def start_preparing(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Restaurant":
        return envelope.forbidden()
    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if user_id != order["restaurant_id"]:
            return envelope.forbidden()
        if order["status"] != "RESTAURANT_ACCEPTED":
            return envelope.invalid_state(
                "Order must be RESTAURANT_ACCEPTED to start preparing."
            )
        order["status"] = "PREPARING"
        svc.bump(order)
        # Open dispatch offer; failure here doesn't roll back state — the
        # admin or CS can re-dispatch explicitly.
        dispatch_svc.dispatch_for_order(order)
        return envelope.success(projection.render(order))


@bp.route("/api/orders/<oid>/ready", methods=["POST"])
def order_ready(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Restaurant":
        return envelope.forbidden()
    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if user_id != order["restaurant_id"]:
            return envelope.forbidden()
        if order["status"] != "PREPARING":
            return envelope.invalid_state(
                "Order must be PREPARING to mark ready."
            )
        # A rider must be ACCEPTED or PICKED_UP on this order.
        has_accepted = any(
            a["order_id"] == oid and a["status"] in ("ACCEPTED", "PICKED_UP")
            for a in state.STORE.assignments.values()
        )
        if not has_accepted:
            return envelope.invalid_state(
                "No rider has accepted this order yet."
            )
        order["status"] = "READY_FOR_PICKUP"
        svc.bump(order)
        return envelope.success(projection.render(order))


@bp.route("/api/orders/<oid>/dispatch", methods=["POST"])
def order_dispatch(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        order = state.STORE.orders.get(oid)
        if order is None:
            return envelope.not_found("Order not found.")
        if order["status"] not in (
            "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
        ):
            return envelope.invalid_state(
                "Order not in a state that accepts a fresh dispatch."
            )
        new_assignment = dispatch_svc.dispatch_for_order(order)
        if new_assignment is None:
            return envelope.invalid_state(
                "No candidate riders are available for this order."
            )
        return envelope.created(projection.render(new_assignment))


@bp.route("/api/orders/<oid>/returns", methods=["POST"])
def open_return(oid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Customer":
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    return returns_svc.open_return(oid, user_id, payload)
