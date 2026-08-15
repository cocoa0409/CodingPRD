"""RouteStop endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, req_field, make_entity, touch, lookup,
    list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN_FOR_ROLE,
    ERR_PLANNED_QTY_MISMATCH, ERR_FRESHNESS_WINDOW_VIOLATION, ERR_NOT_FOUND,
)
from services.calculations import stocking_allocation, parse_iso_z
from services.cascades import cascade_stop_reconciled

bp = Blueprint("route_stops", __name__)


def _serialize(stop):
    return dict(stop)


@bp.route("/bakery/route-stops", methods=["POST"])
def create_stop():
    _, role = get_auth()
    require_role(role, {"Planner"})
    data = body()
    route_id = req_string(data, "route_id")
    route = lookup(DB.routes, route_id, "route")
    store_order_id = req_string(data, "store_order_id")
    order = lookup(DB.store_orders, store_order_id, "store order")
    planned_units = req_int(data, "planned_units", min_value=1)
    batch_ids = req_field(data, "batch_ids")
    if not isinstance(batch_ids, list) or not batch_ids:
        raise ApiError(ERR_INVALID_REQUEST, "batch_ids must be a non-empty array", 400)
    batches = []
    for bid in batch_ids:
        if not isinstance(bid, str):
            raise ApiError(ERR_INVALID_REQUEST, "batch_ids must be strings", 400)
        b = DB.batches.get(bid)
        if b is None:
            raise ApiError(ERR_NOT_FOUND, f"batch {bid} not found", 404)
        batches.append(b)

    if route.get("status") != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Route is not PLANNED", 409)
    if order.get("status") not in ("CONFIRMED", "LOCKED", "SHORTED"):
        raise ApiError(ERR_INVALID_STATE, "Order must be CONFIRMED, LOCKED, or SHORTED", 409)
    if planned_units != int(order.get("total_units") or 0):
        raise ApiError(ERR_PLANNED_QTY_MISMATCH, "planned_units != order total_units", 409)

    # Every batch RELEASED
    for b in batches:
        if b.get("status") != "RELEASED":
            raise ApiError(ERR_INVALID_REQUEST, "Every batch must be RELEASED", 400)

    # Cover every order-line product
    needed_products = {ln["product_id"] for ln in (order.get("lines") or [])}
    covered_products = {b.get("product_id") for b in batches}
    if not needed_products.issubset(covered_products):
        raise ApiError(ERR_INVALID_REQUEST, "batch_ids do not cover all order-line products", 400)

    stop = make_entity({
        "route_id": route_id,
        "store_order_id": store_order_id,
        "store_id": order.get("store_id"),
        "planned_units": planned_units,
        "batch_ids": list(batch_ids),
        "status": "PENDING",
        "delivered_units": None,
        "on_shelf_units_observed": None,
        "stocked_units": None,
        "refused_units": None,
        "shortfall_flag": False,
    })
    DB.route_stops[stop["id"]] = stop
    return success_object(_serialize(stop), status=201)


@bp.route("/bakery/route-stops/<sid>", methods=["GET"])
def get_stop(sid):
    get_auth()
    stop = lookup(DB.route_stops, sid, "route stop")
    return success_object(_serialize(stop))


@bp.route("/bakery/route-stops", methods=["GET"])
def list_stops():
    get_auth()
    filters = {
        "route_id": request.args.get("route_id"),
        "store_id": request.args.get("store_id"),
        "store_order_id": request.args.get("store_order_id"),
        "status": request.args.get("status"),
    }
    return list_response([_serialize(s) for s in DB.route_stops.values()], filters)


@bp.route("/bakery/route-stops/<sid>/deliver", methods=["POST"])
def deliver_stop(sid):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    stop = lookup(DB.route_stops, sid, "route stop")
    route = DB.routes.get(stop.get("route_id"))
    if route is None:
        raise ApiError(ERR_NOT_FOUND, "route not found", 404)
    if user_id != route.get("driver_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Driver does not own this route", 403)
    data = body()
    delivered_units = req_int(data, "delivered_units", min_value=0, allow_zero=True)
    on_shelf_units_observed = req_int(data, "on_shelf_units_observed", min_value=0, allow_zero=True)

    if stop.get("status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Stop is not PENDING", 409)
    if route.get("status") != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, "Route is not DISPATCHED", 409)
    for bid in stop.get("batch_ids") or []:
        b = DB.batches.get(bid)
        if b is None:
            raise ApiError(ERR_NOT_FOUND, f"batch {bid} not found", 404)
        if b.get("status") != "RELEASED":
            raise ApiError(ERR_INVALID_STATE, "Every batch must be RELEASED", 409)
    if delivered_units > int(stop.get("planned_units") or 0):
        raise ApiError(ERR_INVALID_REQUEST, "delivered_units exceeds planned_units", 400)

    # Freshness: clock <= min(fresh_until) - store.min_remaining_life_hours_on_delivery
    store = DB.stores.get(stop.get("store_id"))
    if store is None:
        raise ApiError(ERR_NOT_FOUND, "store not found", 404)
    fresh_list = []
    for bid in stop.get("batch_ids") or []:
        b = DB.batches.get(bid)
        if b is None or b.get("fresh_until") is None:
            continue
        fresh_list.append(parse_iso_z(b["fresh_until"]))
    if fresh_list:
        from datetime import timedelta
        earliest = min(fresh_list)
        threshold = earliest - timedelta(hours=int(store.get("min_remaining_life_hours_on_delivery") or 0))
        if DB.clock > threshold:
            raise ApiError(ERR_FRESHNESS_WINDOW_VIOLATION, "Delivery past freshness window", 409)

    stocked, refused = stocking_allocation(
        delivered_units, on_shelf_units_observed, int(store["shelf_capacity_units"])
    )
    stop["delivered_units"] = delivered_units
    stop["on_shelf_units_observed"] = on_shelf_units_observed
    stop["stocked_units"] = stocked
    stop["refused_units"] = refused
    stop["status"] = "DELIVERED"
    touch(stop)

    route["delivered_units"] = int(route.get("delivered_units") or 0) + delivered_units
    route["refused_units"] = int(route.get("refused_units") or 0) + refused
    touch(route)
    return success_object(_serialize(stop))


@bp.route("/bakery/route-stops/<sid>/skip", methods=["POST"])
def skip_stop(sid):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    stop = lookup(DB.route_stops, sid, "route stop")
    route = DB.routes.get(stop.get("route_id"))
    if route is None:
        raise ApiError(ERR_NOT_FOUND, "route not found", 404)
    if user_id != route.get("driver_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Driver does not own this route", 403)
    if stop.get("status") != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Stop is not PENDING", 409)
    if route.get("status") != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, "Route is not DISPATCHED", 409)
    stop["status"] = "SKIPPED"
    touch(stop)
    return success_object(_serialize(stop))


@bp.route("/bakery/route-stops/<sid>/reconcile", methods=["POST"])
def reconcile_stop(sid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    stop = lookup(DB.route_stops, sid, "route stop")
    if stop.get("status") != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, "Stop is not DELIVERED", 409)
    stop["status"] = "RECONCILED"
    touch(stop)
    cascade_stop_reconciled(stop)
    return success_object(_serialize(stop))
