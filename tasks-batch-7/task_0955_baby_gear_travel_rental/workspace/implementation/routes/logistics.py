from datetime import timedelta

from flask import Blueprint, request

import calc
import services
from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_route, ser_stop
from util import midnight, parse_date, parse_dt
from validate import req_enum, req_num, req_str

bp = Blueprint("logistics", __name__)

STOP_TYPES = ("DELIVERY_SETUP", "PICKUP")
TERMINAL_STOP_STATES = ("COMPLETED", "FAILED", "SKIPPED")


def _get_route(rid):
    r = store.routes.get(rid)
    if r is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND", 404, "Delivery route not found")
    return r


def _get_stop(sid):
    s = store.stops.get(sid)
    if s is None:
        raise ApiError("ERR_STOP_NOT_FOUND", 404, "Route stop not found")
    return s


@bp.post("/routes")
def create_route():
    require_roles("OperationsAdmin")
    b = body()
    rdate = parse_date(b.get("route_date"))
    if rdate is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "route_date must be YYYY-MM-DD")
    zone = req_str(b, "zone_code")
    capacity = req_num(b, "vehicle_capacity_kg")
    if capacity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "vehicle_capacity_kg must be > 0")
    rec = create_rec(store.routes, {
        "route_date": rdate, "zone_code": zone,
        "vehicle_capacity_kg": capacity, "status": "PLANNED",
        "planned_weight_kg": 0})
    return ok_obj(ser_route(rec), 201)


@bp.get("/routes/<rid>")
def get_route(rid):
    require_roles("Inspector", "OperationsAdmin")
    return ok_obj(ser_route(_get_route(rid)))


@bp.get("/routes")
def list_routes():
    require_roles("Inspector", "OperationsAdmin")
    recs = sorted_ords(list(store.routes.values()))
    rdate = request.args.get("route_date")
    if rdate is not None:
        recs = [r for r in recs if r["route_date"].isoformat() == rdate]
    zone = request.args.get("zone_code")
    if zone is not None:
        recs = [r for r in recs if r["zone_code"] == zone]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_route)


@bp.post("/routes/<rid>/stops")
def add_stop(rid):
    require_roles("OperationsAdmin")
    route = _get_route(rid)  # path id validated before body references
    b = body()
    res_id = b.get("reservation_id")
    if not isinstance(res_id, str) or not res_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "reservation_id is required")
    res = store.reservations.get(res_id)
    if res is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", 404, "Reservation not found")
    stop_type = req_enum(b, "stop_type", STOP_TYPES)
    address = req_str(b, "address")
    w_start = parse_dt(b.get("time_window_start"))
    w_end = parse_dt(b.get("time_window_end"))
    if w_start is None or w_end is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "time_window_start/time_window_end must be ISO 8601")
    # Date/window sanity: window within route_date, start strictly before end
    day_start = midnight(route["route_date"])
    day_end = day_start + timedelta(days=1)
    if w_start >= w_end or w_start < day_start or w_end > day_end:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422,
                       "Stop window must lie within route_date with start < end")
    # State
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Stops may only be added to a PLANNED route")
    # Temporal: half-open window conflict with other non-skipped stops
    for stop in store.stops.values():
        if (stop["route_id"] == route["id"] and stop["status"] != "SKIPPED"
                and w_start < stop["time_window_end_dt"]
                and stop["time_window_start_dt"] < w_end):
            raise ApiError("ERR_STOP_WINDOW_CONFLICT", 409,
                           "Stop window overlaps another stop on this route")
    # Structural: zone match, then duplicate, then capacity
    if res["zone_code"] != route["zone_code"]:
        raise ApiError("ERR_ZONE_MISMATCH", 422,
                       "Stop reservation zone must equal the route zone")
    for stop in store.stops.values():
        if (stop["reservation_id"] == res["id"] and stop["stop_type"] == stop_type
                and stop["status"] in ("SCHEDULED", "COMPLETED")
                and store.routes[stop["route_id"]]["status"] in ("PLANNED", "DISPATCHED")):
            raise ApiError("ERR_DUPLICATE_STOP", 409,
                           "Same reservation and stop_type already scheduled")
    weight = calc.stop_weight(res)
    new_weight = route["planned_weight_kg"] + weight
    if new_weight > route["vehicle_capacity_kg"] + 1e-9:  # exact fit allowed
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 422,
                       "Stop would exceed vehicle capacity")
    rec = create_rec(store.stops, {
        "route_id": route["id"], "reservation_id": res["id"],
        "stop_type": stop_type, "address": address,
        "time_window_start_dt": w_start, "time_window_end_dt": w_end,
        "status": "SCHEDULED", "sequence": 0, "completed_at": None})
    calc.recompute_route_weight(route)
    calc.resequence_stops(route["id"])
    bump(route)
    return ok_obj(ser_stop(rec), 201)


@bp.get("/routes/<rid>/stops")
def list_route_stops(rid):
    require_roles("Inspector", "OperationsAdmin")
    route = _get_route(rid)
    recs = [s for s in store.stops.values() if s["route_id"] == route["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    # Route stops follow stop sequencing (time window order), not created_at
    recs.sort(key=lambda s: (s["sequence"] if s["status"] != "SKIPPED" else 1 << 30,
                             s["_ord"]))
    return paginate(recs, ser_stop)


@bp.post("/routes/<rid>/dispatch")
def dispatch_route(rid):
    require_roles("OperationsAdmin")
    route = _get_route(rid)
    if route["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Route is not PLANNED")
    if not any(s["route_id"] == route["id"] and s["status"] == "SCHEDULED"
               for s in store.stops.values()):
        raise ApiError("ERR_INVALID_STATE", 409, "Route has no SCHEDULED stop")
    route["status"] = "DISPATCHED"
    bump(route)
    return ok_obj(ser_route(route))


@bp.post("/routes/<rid>/recall")
def recall_route(rid):
    require_roles("OperationsAdmin")
    route = _get_route(rid)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Route is not DISPATCHED")
    if any(s["route_id"] == route["id"] and s["status"] == "COMPLETED"
           for s in store.stops.values()):
        raise ApiError("ERR_INVALID_STATE", 409, "Route has a COMPLETED stop")
    route["status"] = "PLANNED"
    bump(route)
    return ok_obj(ser_route(route))


@bp.post("/routes/<rid>/complete")
def complete_route(rid):
    require_roles("OperationsAdmin")
    route = _get_route(rid)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Route is not DISPATCHED")
    if any(s["route_id"] == route["id"] and s["status"] not in TERMINAL_STOP_STATES
           for s in store.stops.values()):
        raise ApiError("ERR_INVALID_STATE", 409, "Not every stop is in a terminal state")
    route["status"] = "COMPLETED"
    bump(route)
    return ok_obj(ser_route(route))


@bp.get("/route-stops/<sid>")
def get_stop(sid):
    require_roles("Inspector", "OperationsAdmin")
    return ok_obj(ser_stop(_get_stop(sid)))


@bp.get("/route-stops")
def list_stops():
    require_roles("Inspector", "OperationsAdmin")
    recs = sorted_ords(list(store.stops.values()))
    for param, field in (("route_id", "route_id"),
                         ("reservation_id", "reservation_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [s for s in recs if s[field] == v]
    return paginate(recs, ser_stop)


@bp.post("/route-stops/<sid>/complete")
def complete_stop(sid):
    require_roles("OperationsAdmin")
    stop = _get_stop(sid)
    services.complete_stop(stop)
    return ok_obj(ser_stop(stop))


@bp.post("/route-stops/<sid>/fail")
def fail_stop(sid):
    require_roles("OperationsAdmin")
    stop = _get_stop(sid)
    if stop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Stop is not SCHEDULED")
    route = store.routes[stop["route_id"]]
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Route is not DISPATCHED")
    stop["status"] = "FAILED"
    bump(stop)
    calc.recompute_route_weight(route)
    bump(route)
    return ok_obj(ser_stop(stop))
