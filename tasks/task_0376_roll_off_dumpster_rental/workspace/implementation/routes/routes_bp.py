"""Route endpoints (PRD section 3.6)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import get_route, get_stop, paginate
from middleware import require_auth, require_role
from response import success
import serialize
from serialize import route as ser, route_stop_count
import validate

bp = Blueprint("routes", __name__)


@bp.post("/routes")
def create_route():
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    body = validate.get_json_body()
    validate.require_fields(body, ["service_date", "truck_code", "capacity_stops"])
    service_date = validate.require_date(body, "service_date")
    truck_code = validate.require_string(body, "truck_code")
    capacity_stops = validate.require_int_at_least(body, "capacity_stops", 1)

    # truck_code unique per service_date (priority 15).
    for r in db.routes.values():
        if r["service_date"] == service_date and r["truck_code"] == truck_code:
            raise err("ERR_DUPLICATE_RESOURCE", "truck_code already used on this service_date")

    rec = db.insert_with_common(db.routes, {
        "service_date": service_date,
        "truck_code": truck_code,
        "capacity_stops": capacity_stops,
        "status": "PLANNING",
    })
    return success(ser(rec), status=201)


@bp.get("/routes")
def list_routes():
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher"])
    limit, offset = validate.get_pagination()
    records = list(db.routes.values())
    service_date = request.args.get("service_date")
    status = request.args.get("status")
    if service_date is not None:
        records = [r for r in records if r["service_date"] == service_date]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records, ser, limit, offset)


@bp.get("/routes/<route_id>")
def get_route_ep(route_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher"])
    rec = get_route(route_id)
    return success(ser(rec), status=200)


@bp.get("/routes/<route_id>/stops")
def list_route_stops(route_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher"])
    get_route(route_id)
    limit, offset = validate.get_pagination()
    records = [s for s in db.service_stops.values() if s["route_id"] == route_id]
    return paginate(records, serialize.service_stop, limit, offset)


@bp.post("/routes/<route_id>/stops")
def append_stop(route_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    route = get_route(route_id)
    body = validate.get_json_body()
    validate.require_fields(body, ["service_stop_id", "expected_route_version"])
    service_stop_id = validate.require_string(body, "service_stop_id")
    expected_version = body.get("expected_route_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_route_version must be an integer")

    # existence of body id (priority 3, left-to-right: route already checked).
    stop = get_stop(service_stop_id)

    # state (priority 5): stop UNASSIGNED, route PLANNING.
    if stop["status"] != "UNASSIGNED":
        raise err("ERR_STOP_NOT_UNASSIGNED", "Service stop is not UNASSIGNED")
    if route["status"] != "PLANNING":
        raise err("ERR_ROUTE_NOT_PLANNING", "Route is not PLANNING")

    # capacity (priority 9).
    current_count = route_stop_count(route_id)
    if current_count >= route["capacity_stops"]:
        raise err("ERR_ROUTE_AT_CAPACITY", "Route is at capacity")

    # OCC (priority: stale version check on this write).
    if expected_version != route["version"]:
        raise err("ERR_STALE_ROUTE_VERSION", "Route version is stale")

    # Apply: append last.
    stop["route_id"] = route_id
    stop["sequence"] = current_count + 1
    stop["status"] = "ASSIGNED"
    db.touch(stop)
    db.touch(route)
    return success(serialize.service_stop(stop), status=200)


@bp.post("/routes/<route_id>/dispatch")
def dispatch_route(route_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    route = get_route(route_id)
    if route["status"] != "PLANNING":
        raise err("ERR_ROUTE_NOT_PLANNING", "Route is not PLANNING")
    if route_stop_count(route_id) < 1:
        raise err("ERR_ROUTE_EMPTY", "Route has no stops")
    route["status"] = "DISPATCHED"
    db.touch(route)
    return success(ser(route), status=200)


@bp.post("/routes/<route_id>/close")
def close_route(route_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    route = get_route(route_id)
    if route["status"] != "DISPATCHED":
        raise err("ERR_ROUTE_NOT_DISPATCHED", "Route is not DISPATCHED")
    for s in db.service_stops.values():
        if s["route_id"] == route_id and s["status"] != "CANCELLED":
            if s["status"] != "COMPLETED":
                raise err("ERR_ROUTE_HAS_OPEN_STOPS", "Route has open stops")
    route["status"] = "CLOSED"
    db.touch(route)
    return success(ser(route), status=200)
