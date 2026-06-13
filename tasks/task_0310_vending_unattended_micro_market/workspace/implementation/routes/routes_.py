"""RestockRoute endpoints (PRD 3.4): create, list, get, dispatch, close.

Also holds the /routes/{id}/stops create+list endpoints (route-scoped).
"""
from flask import Blueprint, request

from common import (get_json_body, get_or_404, list_response, require_int,
                    require_str)
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("routes_", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/routes", methods=["POST"])
@require_roles("FieldOps")
def create_route():
    body = get_json_body()
    driver_id = require_str(body, "driver_id")
    service_date = require_str(body, "service_date")

    # FK existence (priority 4)
    if db.drivers.get(driver_id) is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND", "Driver not found")

    obj = {
        "driver_id": driver_id,
        "service_date": service_date,
        "status": "DRAFT",
    }
    stamp_create(obj)
    db.routes[obj["id"]] = obj
    return object_response(serialize.route(obj), 201)


@bp.route("/operations/routes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_routes():
    rows = list(db.routes.values())
    driver_id = request.args.get("driver_id")
    if driver_id is not None:
        rows = [r for r in rows if r["driver_id"] == driver_id]
    return list_response(rows, serialize.route)


@bp.route("/operations/routes/<route_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_route(route_id):
    obj = get_or_404("routes", route_id)
    return object_response(serialize.route(obj))


@bp.route("/operations/routes/<route_id>/stops", methods=["POST"])
@require_roles("FieldOps")
def add_stop(route_id):
    route = get_or_404("routes", route_id)
    body = get_json_body()
    machine_id = require_str(body, "machine_id")
    window_start = require_int(body, "window_start_min")
    window_end = require_int(body, "window_end_min")

    # FK existence (priority 4)
    if db.machines.get(machine_id) is None:
        raise ApiError("ERR_MACHINE_NOT_FOUND", "Machine not found")

    # window validity
    if not (0 <= window_start < 1440):
        raise ApiError("ERR_INVALID_REQUEST", "window_start_min out of range")
    if not (window_start < window_end <= 1440):
        raise ApiError("ERR_INVALID_REQUEST", "window_end_min out of range")

    # business_temporal (priority 9): no overlap with another stop for the
    # SAME driver on the SAME service_date. Half-open; touching allowed.
    for other in db.stops.values():
        other_route = db.routes.get(other["route_id"])
        if other_route is None:
            continue
        if other_route["driver_id"] != route["driver_id"]:
            continue
        if other_route["service_date"] != route["service_date"]:
            continue
        if window_start < other["window_end_min"] and other["window_start_min"] < window_end:
            raise ApiError("ERR_DRIVER_WINDOW_OVERLAP",
                           "Stop window overlaps another stop for the same driver")

    obj = {
        "route_id": route_id,
        "machine_id": machine_id,
        "window_start_min": window_start,
        "window_end_min": window_end,
        "prekit_json": None,
        "status": "PLANNED",
    }
    stamp_create(obj)
    db.stops[obj["id"]] = obj
    return object_response(serialize.stop(obj), 201)


@bp.route("/operations/routes/<route_id>/stops", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_route_stops(route_id):
    get_or_404("routes", route_id)
    rows = [s for s in db.stops.values() if s["route_id"] == route_id]
    return list_response(rows, serialize.stop)


@bp.route("/operations/routes/<route_id>/dispatch", methods=["POST"])
@require_roles("FieldOps")
def dispatch_route(route_id):
    route = get_or_404("routes", route_id)

    # state (priority 5): route must be DRAFT to dispatch. Not a named error in the
    # catalogue beyond the cross-entity guards; treat empty/inactive as the named
    # business errors per PRD 3.4.
    stops = [s for s in db.stops.values() if s["route_id"] == route_id]
    if len(stops) < 1:
        raise ApiError("ERR_ROUTE_EMPTY", "Route has no stops")

    driver = db.drivers.get(route["driver_id"])
    if driver is None or driver["status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_INACTIVE", "Assigned driver is not active")

    # side effects: compute prekit_json per stop over ACTIVE slots
    for stop in stops:
        prekit = {}
        for slot in db.slots.values():
            if slot["machine_id"] != stop["machine_id"]:
                continue
            if slot["status"] != "ACTIVE":
                continue
            prekit[slot["id"]] = max(0, slot["par_level"] - slot["on_hand"])
        stop["prekit_json"] = prekit
        stop["status"] = "KITTED"
        touch(stop)

    route["status"] = "DISPATCHED"
    touch(route)
    return object_response(serialize.route(route))


@bp.route("/operations/routes/<route_id>/close", methods=["POST"])
@require_roles("FieldOps")
def close_route(route_id):
    route = get_or_404("routes", route_id)
    stops = [s for s in db.stops.values() if s["route_id"] == route_id]
    for stop in stops:
        if stop["status"] not in ("VISITED", "SKIPPED"):
            raise ApiError("ERR_STOPS_UNRESOLVED", "Not all stops resolved")
    route["status"] = "CLOSED"
    touch(route)
    return object_response(serialize.route(route))
