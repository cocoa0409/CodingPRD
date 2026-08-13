"""Route endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, parse_iso_datetime, parse_iso_date, make_entity,
    touch, lookup, list_response, public, iso_z,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN_FOR_ROLE,
    ERR_DRIVER_WINDOW_OVERLAP, ERR_STOPS_NOT_LOCKED, ERR_ROUTE_CAPACITY_EXCEEDED,
    ERR_SHRINK_LIMIT_EXCEEDED, ERR_NOT_FOUND,
)
from services.calculations import compute_route_settlement, parse_iso_z

bp = Blueprint("routes", __name__)

REST_BUFFER_MINUTES = 30
ACTIVE_ROUTE_STATES = ("PLANNED", "LOADING", "DISPATCHED", "COMPLETED")


def _serialize(route):
    return dict(route)


@bp.route("/bakery/routes", methods=["POST"])
def create_route():
    _, role = get_auth()
    require_role(role, {"Planner"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    driver_id = req_string(data, "driver_id")
    lookup(DB.drivers, driver_id, "driver")
    route_date = req_string(data, "route_date")
    parse_iso_date(route_date, "route_date")
    window_start_at = req_string(data, "window_start_at")
    window_end_at = req_string(data, "window_end_at")
    start_dt = parse_iso_datetime(window_start_at, "window_start_at")
    end_dt = parse_iso_datetime(window_end_at, "window_end_at")
    if end_dt <= start_dt:
        raise ApiError(ERR_INVALID_REQUEST, "window_end_at must be after window_start_at", 400)
    truck_capacity_units = req_int(data, "truck_capacity_units", min_value=1)

    # Driver rest buffer: same driver, active route, windows within 30 min.
    buffer = timedelta(minutes=REST_BUFFER_MINUTES)
    for other in DB.routes.values():
        if other.get("driver_id") != driver_id:
            continue
        if other.get("status") not in ACTIVE_ROUTE_STATES:
            continue
        o_start = parse_iso_z(other["window_start_at"])
        o_end = parse_iso_z(other["window_end_at"])
        if start_dt < o_end + buffer and end_dt > o_start - buffer:
            raise ApiError(ERR_DRIVER_WINDOW_OVERLAP, "Driver window conflicts within rest buffer", 409)

    route = make_entity({
        "plant_id": plant_id,
        "driver_id": driver_id,
        "route_date": route_date,
        "window_start_at": iso_z(start_dt),
        "window_end_at": iso_z(end_dt),
        "truck_capacity_units": truck_capacity_units,
        "status": "PLANNED",
        "loaded_units": 0,
        "delivered_units": 0,
        "refused_units": 0,
        "returned_stale_units": 0,
        "shrink_units": None,
        "shrink_liability_cents": None,
    })
    DB.routes[route["id"]] = route
    return success_object(_serialize(route), status=201)


@bp.route("/bakery/routes/<rid>", methods=["GET"])
def get_route(rid):
    get_auth()
    route = lookup(DB.routes, rid, "route")
    return success_object(_serialize(route))


@bp.route("/bakery/routes", methods=["GET"])
def list_routes():
    get_auth()
    filters = {
        "plant_id": request.args.get("plant_id"),
        "driver_id": request.args.get("driver_id"),
        "route_date": request.args.get("route_date"),
    }
    return list_response([_serialize(r) for r in DB.routes.values()], filters)


def _require_driver_ownership(user_id, route):
    if user_id != route.get("driver_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Driver does not own this route", 403)


@bp.route("/bakery/routes/<rid>/start-loading", methods=["POST"])
def start_loading(rid):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    route = lookup(DB.routes, rid, "route")
    _require_driver_ownership(user_id, route)
    if route.get("status") != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Route is not PLANNED", 409)
    stops = [s for s in DB.route_stops.values() if s.get("route_id") == rid]
    if not stops:
        raise ApiError(ERR_INVALID_STATE, "Route has no stops", 409)
    for s in stops:
        order = DB.store_orders.get(s.get("store_order_id"))
        if order is None:
            raise ApiError(ERR_NOT_FOUND, "order not found", 404)
        if order.get("status") not in ("LOCKED", "SHORTED"):
            raise ApiError(ERR_STOPS_NOT_LOCKED, "Every stop's order must be LOCKED or SHORTED", 409)
    route["loaded_units"] = sum(int(s.get("planned_units") or 0) for s in stops)
    route["status"] = "LOADING"
    touch(route)
    return success_object(_serialize(route))


@bp.route("/bakery/routes/<rid>/dispatch", methods=["POST"])
def dispatch_route(rid):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    route = lookup(DB.routes, rid, "route")
    _require_driver_ownership(user_id, route)
    if route.get("status") != "LOADING":
        raise ApiError(ERR_INVALID_STATE, "Route is not LOADING", 409)
    if int(route.get("loaded_units") or 0) > int(route["truck_capacity_units"]):
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, "loaded_units exceeds truck capacity", 409)
    route["status"] = "DISPATCHED"
    touch(route)
    return success_object(_serialize(route))


@bp.route("/bakery/routes/<rid>/complete", methods=["POST"])
def complete_route(rid):
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    route = lookup(DB.routes, rid, "route")
    _require_driver_ownership(user_id, route)
    if route.get("status") != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, "Route is not DISPATCHED", 409)
    for s in DB.route_stops.values():
        if s.get("route_id") != rid:
            continue
        if s.get("status") not in ("DELIVERED", "SKIPPED", "RECONCILED"):
            raise ApiError(ERR_INVALID_STATE, "Not all stops are in a terminal delivery state", 409)
    route["status"] = "COMPLETED"
    touch(route)
    return success_object(_serialize(route))


@bp.route("/bakery/routes/<rid>/settle", methods=["POST"])
def settle_route(rid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    route = lookup(DB.routes, rid, "route")
    if route.get("status") != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, "Route is not COMPLETED", 409)
    data = {}
    if request.is_json:
        body_data = request.get_json(silent=True)
        if isinstance(body_data, dict):
            data = body_data
    override = data.get("override_shrink_limit", False)

    delivered, refused, returned_stale, shrink_units, shrink_pct, liability_units, liability_cents = (
        compute_route_settlement(route)
    )

    from decimal import Decimal
    if shrink_pct > Decimal("0.10") and not override:
        raise ApiError(ERR_SHRINK_LIMIT_EXCEEDED, "Shrink ratio exceeds hard limit", 409)

    route["delivered_units"] = delivered
    route["refused_units"] = refused
    route["returned_stale_units"] = returned_stale
    route["shrink_units"] = shrink_units
    route["shrink_liability_cents"] = liability_cents
    route["status"] = "SETTLED"
    touch(route)

    driver = DB.drivers.get(route.get("driver_id"))
    if driver is not None:
        driver["shrink_liability_cents"] = int(driver.get("shrink_liability_cents") or 0) + liability_cents
        touch(driver)

    for s in DB.route_stops.values():
        if s.get("route_id") != rid:
            continue
        store = DB.stores.get(s.get("store_id"))
        if store is None:
            continue
        store["lifetime_delivered_units"] = int(store.get("lifetime_delivered_units") or 0) + int(s.get("delivered_units") or 0)
        touch(store)

    return success_object(_serialize(route))


@bp.route("/bakery/routes/<rid>/cancel", methods=["POST"])
def cancel_route(rid):
    _, role = get_auth()
    require_role(role, {"Planner"})
    route = lookup(DB.routes, rid, "route")
    if route.get("status") != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Route is not PLANNED", 409)
    has_stops = any(s.get("route_id") == rid for s in DB.route_stops.values())
    if has_stops:
        raise ApiError(ERR_INVALID_STATE, "Route has stops", 409)
    route["status"] = "CANCELLED"
    touch(route)
    return success_object(_serialize(route))
