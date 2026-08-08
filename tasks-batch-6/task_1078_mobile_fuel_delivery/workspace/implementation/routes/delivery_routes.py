from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  check_enum, as_int, parse_dt, ok, ok_list, paginate,
                  sorted_records, base_record, touch)
from serializers import ser_route
from domain import get_truck, get_route, release_reservation

bp = Blueprint("delivery_routes", __name__)

NON_TERMINAL_ROUTE = {"PLANNING", "DISPATCHED"}


def _overlaps(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@bp.post("/routes")
def create_route():
    uid, role = get_auth()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["truck_id", "assigned_driver_id", "zone", "window_start", "window_end"])
    check_enum(body["zone"], store.ZONES, "zone")
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    max_stops = 8
    if "max_stops" in body and body["max_stops"] is not None:
        max_stops = as_int(body["max_stops"], "max_stops", minimum=1)
    get_truck(body["truck_id"])
    # temporal overlap on the same truck's non-terminal routes
    for r in DB.routes.values():
        if r["truck_id"] == body["truck_id"] and r["status"] in NON_TERMINAL_ROUTE:
            if _overlaps(ws, we, r["window_start"], r["window_end"]):
                raise ApiError("ERR_TRUCK_ROUTE_OVERLAP", "Truck route window overlap")
    rec = base_record()
    rec.update({
        "truck_id": body["truck_id"],
        "assigned_driver_id": body["assigned_driver_id"],
        "zone": body["zone"],
        "window_start": ws,
        "window_end": we,
        "max_stops": max_stops,
        "stop_count": 0,
        "status": "PLANNING",
    })
    DB.routes[rec["id"]] = rec
    return ok(ser_route(rec), status=201)


@bp.get("/routes")
def list_routes():
    uid, role = get_auth()
    require_role(role, {"Dispatcher", "Driver", "PlatformAdmin"})
    items = sorted_records(DB.routes)
    tid = request.args.get("truck_id")
    st = request.args.get("status")
    zone = request.args.get("zone")
    if tid:
        items = [r for r in items if r["truck_id"] == tid]
    if st:
        items = [r for r in items if r["status"] == st]
    if zone:
        items = [r for r in items if r["zone"] == zone]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_route(r) for r in page], total, limit, offset)


@bp.get("/routes/<rid>")
def get_route_ep(rid):
    uid, role = get_auth()
    require_role(role, {"Dispatcher", "Driver", "PlatformAdmin"})
    r = get_route(rid)
    return ok(ser_route(r))


@bp.post("/routes/<rid>/dispatch")
def dispatch_route(rid):
    uid, role = get_auth()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    if r["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_ROUTE_STATE", "Route not PLANNING")
    truck = DB.trucks.get(r["truck_id"])
    if not truck or truck["status"] != "AVAILABLE":
        raise ApiError("ERR_TRUCK_UNAVAILABLE", "Truck not AVAILABLE")
    if r["stop_count"] < 1:
        raise ApiError("ERR_INVALID_ROUTE_STATE", "Route has no stops")
    r["status"] = "DISPATCHED"
    touch(r)
    truck["status"] = "ON_ROUTE"
    touch(truck)
    for o in DB.orders.values():
        if o["route_id"] == rid and o["status"] == "ROUTED":
            o["status"] = "EN_ROUTE"
            touch(o)
    return ok(ser_route(r))


@bp.post("/routes/<rid>/complete")
def complete_route(rid):
    uid, role = get_auth()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    if r["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_ROUTE_STATE", "Route not DISPATCHED")
    for o in DB.orders.values():
        if o["route_id"] == rid and o["status"] in ("EN_ROUTE", "ARRIVED"):
            raise ApiError("ERR_INVALID_ROUTE_STATE", "Route has orders still in flight")
    r["status"] = "COMPLETED"
    touch(r)
    truck = DB.trucks.get(r["truck_id"])
    if truck and truck["status"] == "ON_ROUTE":
        truck["status"] = "AVAILABLE"
        touch(truck)
    return ok(ser_route(r))


@bp.post("/routes/<rid>/cancel")
def cancel_route(rid):
    uid, role = get_auth()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    if r["status"] not in ("PLANNING", "DISPATCHED"):
        raise ApiError("ERR_INVALID_ROUTE_STATE", "Route cannot be cancelled from %s" % r["status"])
    truck = DB.trucks.get(r["truck_id"])
    if truck and truck["status"] == "ON_ROUTE":
        truck["status"] = "AVAILABLE"
        touch(truck)
    for o in DB.orders.values():
        if o["route_id"] == rid and o["status"] in ("ROUTED", "EN_ROUTE"):
            release_reservation(o)
            o["route_id"] = None
            o["status"] = "SCHEDULED"
            touch(o)
    r["stop_count"] = 0
    r["status"] = "CANCELLED"
    touch(r)
    return ok(ser_route(r))
