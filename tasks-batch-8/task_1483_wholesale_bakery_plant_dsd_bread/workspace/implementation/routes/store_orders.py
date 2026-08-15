"""StoreOrder endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_field, parse_iso_date, make_entity, touch, lookup,
    list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN_FOR_ROLE,
    ERR_STALE_VERSION, ERR_ORDER_CUTOFF_PASSED, ERR_STORE_SUSPENDED, ERR_NOT_FOUND,
)
from services.calculations import clock_at_or_before_cutoff

bp = Blueprint("store_orders", __name__)


def _validate_lines(lines, plant_id):
    if not isinstance(lines, list) or not lines:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
    total = 0
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each line must be an object", 400)
        pid = ln.get("product_id")
        qty = ln.get("qty")
        if not isinstance(pid, str) or not pid:
            raise ApiError(ERR_INVALID_REQUEST, "line product_id required", 400)
        product = DB.products.get(pid)
        if product is None:
            raise ApiError(ERR_NOT_FOUND, f"product {pid} not found", 404)
        if product.get("plant_id") != plant_id:
            raise ApiError(ERR_INVALID_REQUEST, "product does not belong to same plant", 400)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "line qty must be a positive integer", 400)
        total += qty
    return total


def _compute_total(lines):
    return sum(int(ln["qty"]) for ln in (lines or []))


def _serialize(order):
    out = dict(order)
    return out


@bp.route("/bakery/store-orders", methods=["POST"])
def create_order():
    _, role = get_auth()
    require_role(role, {"Planner", "PlantAdmin"})
    data = body()
    store_id = req_string(data, "store_id")
    store = lookup(DB.stores, store_id, "store")
    delivery_date = req_string(data, "delivery_date")
    parse_iso_date(delivery_date, "delivery_date")
    lines = req_field(data, "lines")

    total = _validate_lines(lines, store["plant_id"])

    if store.get("status") != "ACTIVE":
        raise ApiError(ERR_STORE_SUSPENDED, "Store is SUSPENDED", 409)

    order = make_entity({
        "store_id": store_id,
        "plant_id": store["plant_id"],
        "delivery_date": delivery_date,
        "lines": [{"product_id": ln["product_id"], "qty": int(ln["qty"])} for ln in lines],
        "pending_lines": None,
        "status": "PLACED",
        "total_units": total,
        "placed_at": DB.clock_iso(),
        "confirmed_at": None,
    })
    DB.store_orders[order["id"]] = order
    return success_object(_serialize(order), status=201)


@bp.route("/bakery/store-orders/<oid>", methods=["GET"])
def get_order(oid):
    get_auth()
    order = lookup(DB.store_orders, oid, "store order")
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders", methods=["GET"])
def list_orders():
    get_auth()
    filters = {
        "store_id": request.args.get("store_id"),
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    }
    return list_response([_serialize(o) for o in DB.store_orders.values()], filters)


@bp.route("/bakery/store-orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    order = lookup(DB.store_orders, oid, "store order")
    if order.get("status") != "PLACED":
        raise ApiError(ERR_INVALID_STATE, "Order is not PLACED", 409)
    store = DB.stores.get(order["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    if store.get("status") != "ACTIVE":
        raise ApiError(ERR_STORE_SUSPENDED, "Store is SUSPENDED", 409)
    if not clock_at_or_before_cutoff(store, order["delivery_date"]):
        raise ApiError(ERR_ORDER_CUTOFF_PASSED, "Clock is past the order cutoff", 409)
    order["status"] = "CONFIRMED"
    order["confirmed_at"] = DB.clock_iso()
    touch(order)
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders/<oid>/request-amendment", methods=["POST"])
def request_amendment(oid):
    user_id, role = get_auth()
    require_role(role, {"StoreReceiver"})
    order = lookup(DB.store_orders, oid, "store order")
    # Ownership: X-User-ID == order.store_id
    if user_id != order.get("store_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "StoreReceiver does not own this order", 403)
    data = body()
    lines = req_field(data, "lines")
    if "expected_store_order_version" not in data:
        raise ApiError(ERR_INVALID_REQUEST, "expected_store_order_version is required", 400)
    expected = data["expected_store_order_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_store_order_version must be an integer", 400)
    total = _validate_lines(lines, order["plant_id"])

    # Optimistic concurrency (§2.9 step 5) precedes state preconditions (step 6)
    if expected != order.get("version"):
        raise ApiError(ERR_STALE_VERSION, "Stale order version", 412)
    if order.get("status") != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Order is not CONFIRMED", 409)
    store = DB.stores.get(order["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    if not clock_at_or_before_cutoff(store, order["delivery_date"]):
        raise ApiError(ERR_ORDER_CUTOFF_PASSED, "Clock is past the order cutoff", 409)

    order["pending_lines"] = [{"product_id": ln["product_id"], "qty": int(ln["qty"])} for ln in lines]
    order["status"] = "AMENDMENT_PENDING"
    touch(order)
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders/<oid>/accept-amendment", methods=["POST"])
def accept_amendment(oid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    order = lookup(DB.store_orders, oid, "store order")
    if order.get("status") != "AMENDMENT_PENDING":
        raise ApiError(ERR_INVALID_STATE, "Order is not AMENDMENT_PENDING", 409)
    order["lines"] = order.get("pending_lines")
    order["pending_lines"] = None
    order["total_units"] = _compute_total(order["lines"])
    order["status"] = "CONFIRMED"
    touch(order)
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders/<oid>/reject-amendment", methods=["POST"])
def reject_amendment(oid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    order = lookup(DB.store_orders, oid, "store order")
    if order.get("status") != "AMENDMENT_PENDING":
        raise ApiError(ERR_INVALID_STATE, "Order is not AMENDMENT_PENDING", 409)
    order["pending_lines"] = None
    order["status"] = "CONFIRMED"
    touch(order)
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders/<oid>/lock", methods=["POST"])
def lock_order(oid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    order = lookup(DB.store_orders, oid, "store order")
    if order.get("status") != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Order is not CONFIRMED", 409)
    store = DB.stores.get(order["store_id"])
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    if not clock_at_or_before_cutoff(store, order["delivery_date"]):
        raise ApiError(ERR_ORDER_CUTOFF_PASSED, "Clock is past the order cutoff", 409)
    order["status"] = "LOCKED"
    touch(order)
    return success_object(_serialize(order))


@bp.route("/bakery/store-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    order = lookup(DB.store_orders, oid, "store order")
    if order.get("status") not in ("PLACED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "Order cannot be cancelled from this state", 409)
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(_serialize(order))
