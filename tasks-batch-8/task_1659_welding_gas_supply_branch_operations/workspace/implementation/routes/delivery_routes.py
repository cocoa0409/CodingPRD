"""Delivery routes and truck capacity."""
from flask import Blueprint

from db import store, new_common, new_id, touch, is_int, parse_date
from errors import ApiError
from middleware import require_roles, body
from response import ok, created

bp = Blueprint("delivery_routes", __name__)


def get_route(rid):
    route = store.delivery_routes.get(rid)
    if route is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DeliveryRoute not found")
    return route


@bp.route("/delivery-routes", methods=["POST"])
@require_roles("CounterRep", "BranchManager")
def create_route():
    b = body()
    route_date = b.get("route_date")
    capacity = b.get("truck_capacity_units")
    try:
        parse_date(route_date)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "route_date must be a YYYY-MM-DD date")
    if not is_int(capacity) or capacity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "truck_capacity_units must be an integer > 0")
    route = {
        "id": new_id(),
        "route_date": route_date,
        "truck_capacity_units": capacity,
        "reserved_units": 0,
        "status": "PLANNED",
    }
    new_common(route)
    store.delivery_routes[route["id"]] = route
    return created(route)


@bp.route("/delivery-routes/<rid>", methods=["GET"])
@require_roles("CounterRep", "BranchManager", "RouteDriver")
def get_one_route(rid):
    return ok(get_route(rid))


@bp.route("/delivery-routes/<rid>/dispatch", methods=["POST"])
@require_roles("RouteDriver", "BranchManager")
def dispatch_route(rid):
    route = get_route(rid)
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PLANNED route can be dispatched")
    route["status"] = "DISPATCHED"
    touch(route)
    return ok(route)


@bp.route("/delivery-routes/<rid>/close", methods=["POST"])
@require_roles("RouteDriver", "BranchManager")
def close_route(rid):
    route = get_route(rid)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DISPATCHED route can be closed")
    # Every bound order must be terminal (FULFILLED or CANCELLED).
    for order in store.orders.values():
        if order["route_id"] == rid and \
                order["fulfillment_status"] not in ("FULFILLED", "CANCELLED"):
            raise ApiError("ERR_ROUTE_HAS_OPEN_ORDERS", 409,
                           "Route still has orders that are not FULFILLED or CANCELLED")
    route["status"] = "CLOSED"
    touch(route)
    return ok(route)
