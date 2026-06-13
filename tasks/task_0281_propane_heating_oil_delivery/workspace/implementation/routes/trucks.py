"""Truck and DeliveryRoute endpoints (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from clock import parse_iso
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_string, require_iso_datetime,
                    optional_int)
from middleware import require_auth, require_role, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("trucks", __name__)


# --- Truck ---

@bp.post("/trucks")
def create_truck():
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    body = get_json_body()
    region_code = require_string(body, "region_code")
    daily_capacity = require_int(body, "daily_capacity_gallons", minimum=1)
    turnaround = optional_int(body, "turnaround_buffer_minutes", default=60, minimum=0)

    rec = {
        "region_code": region_code,
        "daily_capacity_gallons": daily_capacity,
        "turnaround_buffer_minutes": turnaround,
    }
    db.stamp_create_full(rec)
    db.trucks[rec["id"]] = rec
    return object_response(L.serialize_truck(rec), 201)


@bp.get("/trucks/<truck_id>")
def get_truck(truck_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager"})
    rec = L.get_truck(truck_id)
    return object_response(L.serialize_truck(rec), 200)


@bp.get("/trucks")
def list_trucks():
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager"})
    limit, offset = parse_pagination()
    region_code = request.args.get("region_code")

    items = list(db.trucks.values())
    if region_code is not None:
        items = [t for t in items if t.get("region_code") == region_code]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_truck(t) for t in page], limit, offset, total)


# --- DeliveryRoute ---

@bp.post("/trucks/<truck_id>/routes")
def create_route(truck_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    truck = L.get_truck(truck_id)
    body = get_json_body()

    route_date = require_iso_datetime(body, "route_date")
    window_start = require_iso_datetime(body, "window_start")
    window_end = require_iso_datetime(body, "window_end")
    start_dt = parse_iso(window_start)
    end_dt = parse_iso(window_end)
    if not (end_dt > start_dt):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "window_end must be after window_start")

    # Window-conflict check vs other non-cancelled routes on the truck.
    # Closed-interval adjacency: each window is extended by the truck's
    # turnaround buffer on both sides; two windows conflict if they touch or
    # overlap (>= / <=, closed interval).
    buffer = timedelta(minutes=truck.get("turnaround_buffer_minutes", 0))
    new_start = start_dt - buffer
    new_end = end_dt + buffer
    for other in db.routes.values():
        if other["truck_id"] != truck["id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start = parse_iso(other["window_start"])
        o_end = parse_iso(other["window_end"])
        # Conflict when buffered-new touches/overlaps the existing window
        # (closed interval): new_start <= o_end AND o_start <= new_end.
        if new_start <= o_end and o_start <= new_end:
            raise errors.ApiError(errors.ERR_ROUTE_WINDOW_CONFLICT, 409,
                                  "Route window conflicts with another route")

    rec = {
        "truck_id": truck["id"],
        "route_date": route_date,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PLANNING",
        "reserved_gallons": 0,
    }
    db.stamp_create_full(rec)
    db.routes[rec["id"]] = rec
    return object_response(L.serialize_route(rec), 201)


@bp.get("/routes/<route_id>")
def get_route(route_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager", "Driver"})
    rec = L.get_route(route_id)
    return object_response(L.serialize_route(rec), 200)


@bp.get("/routes")
def list_routes():
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager"})
    limit, offset = parse_pagination()
    truck_id = request.args.get("truck_id")
    status = request.args.get("status")
    route_date = request.args.get("route_date")

    items = list(db.routes.values())
    if truck_id is not None:
        items = [r for r in items if r.get("truck_id") == truck_id]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    if route_date is not None:
        items = [r for r in items if r.get("route_date") == route_date]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_route(r) for r in page], limit, offset, total)


@bp.post("/trucks/<truck_id>/routes/<route_id>/dispatch")
def dispatch_route(truck_id, route_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    truck = L.get_truck(truck_id)
    route = L.get_route(route_id)
    if route["truck_id"] != truck["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Route not under truck")

    if route["status"] != "PLANNING":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Route is not PLANNING")
    has_scheduled = any(
        o["status"] == "SCHEDULED" and o.get("route_id") == route["id"]
        for o in db.delivery_orders.values())
    if not has_scheduled:
        raise errors.ApiError(errors.ERR_ROUTE_EMPTY, 409,
                              "Route has no scheduled orders")

    route["status"] = "DISPATCHED"
    db.touch(route)
    return object_response(L.serialize_route(route), 200)


@bp.post("/trucks/<truck_id>/routes/<route_id>/cancel")
def cancel_route(truck_id, route_id):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    truck = L.get_truck(truck_id)
    route = L.get_route(route_id)
    if route["truck_id"] != truck["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Route not under truck")

    status = route["status"]
    if status == "PLANNING":
        pass  # allowed
    elif status == "DISPATCHED":
        # No order on the route may already be DELIVERED.
        for o in db.delivery_orders.values():
            if o.get("route_id") == route["id"] and o["status"] == "DELIVERED":
                raise errors.ApiError(errors.ERR_ROUTE_HAS_DELIVERIES, 409,
                                      "Route already has delivered orders")
    else:
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409,
                              "Route cannot be cancelled from its current state")

    route["status"] = "CANCELLED"

    # Cascade: revert every SCHEDULED order on this route to CREATED, clear
    # route_id, release reservation.
    for o in db.delivery_orders.values():
        if o.get("route_id") == route["id"] and o["status"] == "SCHEDULED":
            o["status"] = "CREATED"
            o["route_id"] = None
            db.touch(o)
    # reserved_gallons recomputed to 0 (no SCHEDULED orders remain on it).
    route["reserved_gallons"] = 0
    db.touch(route)

    return object_response(L.serialize_route(route), 200)
