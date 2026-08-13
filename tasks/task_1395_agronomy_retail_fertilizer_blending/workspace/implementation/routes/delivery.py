"""Truck, DeliveryRoute, DeliveryStop routes."""

from flask import Blueprint, request, g

import db
from errors import (
    not_found, invalid_transition, business,
    ERR_DUPLICATE_ROUTE_FOR_TRUCK_DATE, ERR_TRUCK_CAPACITY_EXCEEDED,
)
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import scaffold_entity, touch, public, now_stamp_helper
from util import (
    get_body, require, optional, reject_unknown, as_string, as_number, as_int,
    parse_pagination, paginate, parse_instant, parse_route_date, D,
)

bp = Blueprint("delivery", __name__)


def _get_truck(tid):
    x = db.trucks.get(tid)
    if x is None:
        raise not_found("Truck not found")
    return x


def _get_route(rid):
    x = db.delivery_routes.get(rid)
    if x is None:
        raise not_found("Delivery route not found")
    return x


def _get_stop(sid):
    x = db.delivery_stops.get(sid)
    if x is None:
        raise not_found("Delivery stop not found")
    return x


# ---------------------------------------------------------------------------
# Trucks
# ---------------------------------------------------------------------------

@bp.post("/agronomy/trucks")
def create_truck():
    require_roles("LogisticsDispatcher")
    body = get_body()
    reject_unknown(body, {"name", "capacity_tons"})
    name = as_string(require(body, "name"), "name")
    capacity = as_number(require(body, "capacity_tons"), "capacity_tons", minimum=0, exclusive_min=True)
    truck = scaffold_entity(db.trucks, {
        "name": name,
        "capacity_tons": float(capacity),
        "status": "ACTIVE",
    })
    return success_object(public(truck), 201)


@bp.get("/agronomy/trucks")
def list_trucks():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.trucks.values())
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/trucks/<truckId>")
def get_truck(truckId):
    require_roles(*ALL_ROLES)
    truck = _get_truck(truckId)
    return success_object(public(truck))


@bp.post("/agronomy/trucks/<truckId>/out-of-service")
def truck_out(truckId):
    require_roles("LogisticsDispatcher")
    truck = _get_truck(truckId)
    if truck["status"] != "ACTIVE":
        raise invalid_transition("Truck not ACTIVE")
    truck["status"] = "OUT_OF_SERVICE"
    touch(truck)
    return success_object(public(truck))


@bp.post("/agronomy/trucks/<truckId>/return-to-service")
def truck_return(truckId):
    require_roles("LogisticsDispatcher")
    truck = _get_truck(truckId)
    if truck["status"] != "OUT_OF_SERVICE":
        raise invalid_transition("Truck not OUT_OF_SERVICE")
    truck["status"] = "ACTIVE"
    touch(truck)
    return success_object(public(truck))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/agronomy/delivery-routes")
def create_route():
    require_roles("LogisticsDispatcher")
    body = get_body()
    reject_unknown(body, {"truck_id", "route_date"})
    truck_id = require(body, "truck_id")
    route_date = parse_route_date(require(body, "route_date"), "route_date")
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise not_found("Truck not found")
    for r in db.delivery_routes.values():
        if r["truck_id"] == truck["id"] and r["route_date"] == route_date \
                and r["status"] != "CANCELLED":
            raise business(ERR_DUPLICATE_ROUTE_FOR_TRUCK_DATE, 409,
                           "A non-cancelled route already exists for the truck on the date")
    route = scaffold_entity(db.delivery_routes, {
        "truck_id": truck["id"],
        "route_date": route_date,
        "total_stop_tons": 0,
        "status": "PLANNED",
    })
    return success_object(public(route), 201)


@bp.get("/agronomy/delivery-routes")
def list_routes():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.delivery_routes.values())
    if "truck_id" in request.args:
        items = [r for r in items if r["truck_id"] == request.args["truck_id"]]
    if "route_date" in request.args:
        items = [r for r in items if r["route_date"] == request.args["route_date"]]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/delivery-routes/<routeId>")
def get_route(routeId):
    require_roles(*ALL_ROLES)
    route = _get_route(routeId)
    return success_object(public(route))


@bp.post("/agronomy/delivery-routes/<routeId>/stops")
def add_stop(routeId):
    require_roles("LogisticsDispatcher")
    route = _get_route(routeId)
    body = get_body()
    reject_unknown(body, {"blend_order_id", "sequence", "window_start", "window_end"})
    order_id = require(body, "blend_order_id")
    sequence = as_int(require(body, "sequence"), "sequence", minimum=1)
    w_start = parse_instant(require(body, "window_start"), "window_start")
    w_end = parse_instant(require(body, "window_end"), "window_end")
    if w_end <= w_start:
        from errors import validation
        raise validation("window_end must be later than window_start")
    order = db.blend_orders.get(order_id)
    if order is None:
        raise not_found("Blend order not found")
    if route["status"] != "PLANNED":
        raise invalid_transition("Route not PLANNED")
    if order["fulfillment_status"] != "BATCHED":
        raise invalid_transition("Order not BATCHED")
    truck = db.trucks[route["truck_id"]]
    stop_tons = D(order["tons_total"])
    if D(route["total_stop_tons"]) + stop_tons > D(truck["capacity_tons"]):
        raise business(ERR_TRUCK_CAPACITY_EXCEEDED, 422, "Truck capacity exceeded")
    stop = scaffold_entity(db.delivery_stops, {
        "delivery_route_id": route["id"],
        "blend_order_id": order["id"],
        "sequence": sequence,
        "window_start": iso8601_ms(w_start),
        "window_end": iso8601_ms(w_end),
        "stop_tons": float(stop_tons),
        "delivered_at": None,
        "status": "PLANNED",
    })
    route["total_stop_tons"] = float(D(route["total_stop_tons"]) + stop_tons)
    touch(route)
    order["fulfillment_status"] = "LOADED"
    touch(order)
    return success_object(public(stop), 201)


@bp.get("/agronomy/delivery-routes/<routeId>/stops")
def list_route_stops(routeId):
    require_roles(*ALL_ROLES)
    route = _get_route(routeId)
    limit, offset = parse_pagination()
    items = [s for s in db.delivery_stops.values() if s["delivery_route_id"] == route["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/agronomy/delivery-routes/<routeId>/dispatch")
def dispatch_route(routeId):
    require_roles("LogisticsDispatcher")
    route = _get_route(routeId)
    if route["status"] != "PLANNED":
        raise invalid_transition("Route not PLANNED")
    planned_stops = [s for s in db.delivery_stops.values()
                     if s["delivery_route_id"] == route["id"] and s["status"] == "PLANNED"]
    if not planned_stops:
        raise invalid_transition("Route has no PLANNED stops")
    truck = db.trucks[route["truck_id"]]
    if truck["status"] != "ACTIVE":
        raise invalid_transition("Truck not ACTIVE")
    route["status"] = "DISPATCHED"
    touch(route)
    return success_object(public(route))


@bp.post("/agronomy/delivery-routes/<routeId>/cancel")
def cancel_route(routeId):
    require_roles("LogisticsDispatcher")
    route = _get_route(routeId)
    if route["status"] != "PLANNED":
        raise invalid_transition("Route not PLANNED")
    route["status"] = "CANCELLED"
    touch(route)
    for s in db.delivery_stops.values():
        if s["delivery_route_id"] == route["id"] and s["status"] == "PLANNED":
            s["status"] = "CANCELLED"
            touch(s)
            order = db.blend_orders.get(s["blend_order_id"])
            if order is not None and order["fulfillment_status"] == "LOADED":
                order["fulfillment_status"] = "BATCHED"
                touch(order)
    return success_object(public(route))


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------

@bp.get("/agronomy/delivery-stops/<stopId>")
def get_stop(stopId):
    require_roles(*ALL_ROLES)
    stop = _get_stop(stopId)
    return success_object(public(stop))


@bp.get("/agronomy/delivery-stops")
def list_stops():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.delivery_stops.values())
    if "blend_order_id" in request.args:
        items = [s for s in items if s["blend_order_id"] == request.args["blend_order_id"]]
    if "delivery_route_id" in request.args:
        items = [s for s in items if s["delivery_route_id"] == request.args["delivery_route_id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/agronomy/delivery-stops/<stopId>/complete")
def complete_stop(stopId):
    require_roles("LogisticsDispatcher")
    stop = _get_stop(stopId)
    body = get_body()
    reject_unknown(body, {"delivered_at"})
    if stop["status"] != "PLANNED":
        raise invalid_transition("Stop not PLANNED")
    route = db.delivery_routes[stop["delivery_route_id"]]
    if route["status"] != "DISPATCHED":
        raise invalid_transition("Route not DISPATCHED")
    delivered_at_input = optional(body, "delivered_at", None)
    if delivered_at_input is not None:
        stop["delivered_at"] = iso8601_ms(parse_instant(delivered_at_input, "delivered_at"))
    else:
        stop["delivered_at"] = now_stamp_helper()
    stop["status"] = "DELIVERED"
    touch(stop)
    order = db.blend_orders.get(stop["blend_order_id"])
    if order is not None and order["fulfillment_status"] == "LOADED":
        order["fulfillment_status"] = "DELIVERED"
        touch(order)
    # route bubble-up
    siblings = [s for s in db.delivery_stops.values()
                if s["delivery_route_id"] == route["id"] and s["status"] != "CANCELLED"]
    if siblings and all(s["status"] == "DELIVERED" for s in siblings):
        route["status"] = "COMPLETED"
        touch(route)
    return success_object(public(stop))
