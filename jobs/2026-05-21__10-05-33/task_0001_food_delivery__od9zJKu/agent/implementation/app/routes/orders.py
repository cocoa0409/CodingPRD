from __future__ import annotations

from flask import Blueprint, g, request

from .. import dispatch, order_logic, projections, resolvers
from ..auth import require_role
from ..envelope import err_forbidden, err_validation, success, success_list
from ..store import store
from ..validators import get_json, pagination_params, require_str

bp = Blueprint("orders", __name__)


def _serialize(o: dict) -> dict:
    return projections.order(o)


@bp.route("/api/orders", methods=["POST"])
def place_order():
    require_role("Customer")
    body = get_json()
    customer_id = body.get("customer_id")
    restaurant_id = body.get("restaurant_id")
    items = body.get("items")
    order = order_logic.place_order(customer_id, restaurant_id, items, actor_user_id=g.user_id)
    return success(_serialize(order), status=201)


@bp.route("/api/orders/<oid>", methods=["GET"])
def read_order(oid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    o = resolvers.order(oid)
    # Identity gate based on role
    if g.user_role == "Customer" and g.user_id != o["customer_id"]:
        raise err_forbidden("Customer identity mismatch")
    if g.user_role == "Restaurant" and g.user_id != o["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    if g.user_role == "Rider":
        # Rider must have at least one assignment on this order
        if not any(
            a["rider_id"] == g.user_id and a["order_id"] == o["id"]
            for a in store.assignments.values()
        ):
            raise err_forbidden("Rider identity mismatch")
    return success(_serialize(o))


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = pagination_params()
    f_customer = request.args.get("customer_id")
    f_restaurant = request.args.get("restaurant_id")
    f_rider = request.args.get("rider_id")
    f_status = request.args.get("status")
    items = list(store.orders.values())
    # Role-based scoping
    if g.user_role == "Customer":
        items = [o for o in items if o["customer_id"] == g.user_id]
    elif g.user_role == "Restaurant":
        items = [o for o in items if o["restaurant_id"] == g.user_id]
    elif g.user_role == "Rider":
        # Orders touched by any assignment of this rider
        my_order_ids = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == g.user_id}
        items = [o for o in items if o["id"] in my_order_ids]
    # Explicit filters apply on top
    if f_customer:
        items = [o for o in items if o["customer_id"] == f_customer]
    if f_restaurant:
        items = [o for o in items if o["restaurant_id"] == f_restaurant]
    if f_rider:
        order_ids = {a["order_id"] for a in store.assignments.values() if a["rider_id"] == f_rider}
        items = [o for o in items if o["id"] in order_ids]
    if f_status:
        items = [o for o in items if o["status"] == f_status]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([_serialize(o) for o in page], limit, offset, total)


@bp.route("/api/orders/<oid>/accept", methods=["POST"])
def accept_order(oid: str):
    require_role("Restaurant")
    o = resolvers.order(oid)
    if g.user_id != o["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    order_logic.restaurant_accept(o)
    return success(_serialize(o))


@bp.route("/api/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid: str):
    require_role("Customer", "Restaurant", "CustomerService")
    o = resolvers.order(oid)
    if g.user_role == "Customer" and g.user_id != o["customer_id"]:
        raise err_forbidden("Customer identity mismatch")
    if g.user_role == "Restaurant" and g.user_id != o["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    order_logic.cancel_order(o)
    return success(_serialize(o))


@bp.route("/api/orders/<oid>/start-preparing", methods=["POST"])
def start_preparing(oid: str):
    require_role("Restaurant")
    o = resolvers.order(oid)
    if g.user_id != o["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    order_logic.restaurant_start_preparing(o)
    # Open a dispatch offer; if no rider available, do NOT roll back: the order remains
    # in PREPARING. The PRD says start-preparing "opens a dispatch offer" — a missing rider
    # is an operational reality, not an order-state failure. We swallow the dispatch error.
    try:
        dispatch.open_dispatch(o)
    except Exception:
        pass
    return success(_serialize(o))


@bp.route("/api/orders/<oid>/ready", methods=["POST"])
def ready_order(oid: str):
    require_role("Restaurant")
    o = resolvers.order(oid)
    if g.user_id != o["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    order_logic.restaurant_ready(o)
    return success(_serialize(o))


@bp.route("/api/orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid: str):
    require_role("PlatformAdmin", "CustomerService")
    o = resolvers.order(oid)
    # State must be in a dispatchable range: RESTAURANT_ACCEPTED / PREPARING / READY_FOR_PICKUP
    if o["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        from ..envelope import err_invalid_state
        raise err_invalid_state(f"Cannot dispatch order in state {o['status']}")
    a = dispatch.open_dispatch(o)
    return success(projections.assignment(a), status=201)
