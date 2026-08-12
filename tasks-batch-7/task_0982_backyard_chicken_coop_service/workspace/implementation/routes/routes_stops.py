"""SittingRoute and RouteStop endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import new_id, serialize, stamp_new, store, touch
from errors import fail
from middleware import (
    ALL_ROLES,
    authenticate,
    body,
    require_role,
    require_tech,
)
from response import list_response, ok
from services.pricing import TRAVEL_BUFFER_MINUTES
from util import buffered_conflict, is_int, midnight, req_dt, req_enum, req_str

bp = Blueprint("routes_stops", __name__)

ZONES = {"URBAN", "SUBURBAN", "RURAL"}


def get_route(rid):
    r = store.routes.get(rid)
    if r is None:
        fail("ERR_ROUTE_NOT_FOUND", f"Sitting route {rid} does not exist")
    return r


def get_stop(sid):
    s = store.stops.get(sid)
    if s is None:
        fail("ERR_STOP_NOT_FOUND", f"Route stop {sid} does not exist")
    return s


@bp.route("/coopcare/sitting-routes", methods=["POST"])
def create_route():
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    data = body()
    technician_id = req_str(data, "technician_id")
    route_date = midnight(req_dt(data, "route_date"))
    zone_code = req_enum(data, "zone_code", ZONES)
    max_stops = data.get("max_stops")
    if not is_int(max_stops):
        fail("ERR_INVALID_REQUEST", "max_stops is required and must be an integer")
    if max_stops <= 0:
        fail("ERR_INVALID_TIME_RANGE", "max_stops must be positive")
    rec = stamp_new({
        "id": new_id(),
        "technician_id": technician_id,
        "route_date": route_date,
        "zone_code": zone_code,
        "max_stops": max_stops,
        "committed_stops": 0,
        "status": "PLANNED",
    })
    store.routes[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/sitting-routes/<rid>", methods=["GET"])
def read_route(rid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_route(rid)), 200)


@bp.route("/coopcare/sitting-routes/<rid>/publish", methods=["POST"])
def publish_route(rid):
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    if r["status"] != "PLANNED":
        fail("ERR_ROUTE_NOT_PLANNED", "publish requires route status PLANNED")
    r["status"] = "PUBLISHED"
    touch(r)
    return ok(serialize(r), 200)


@bp.route("/coopcare/sitting-routes/<rid>/cancel", methods=["POST"])
def cancel_route(rid):
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    if r["status"] not in ("PLANNED", "PUBLISHED"):
        fail("ERR_ROUTE_NOT_PUBLISHED", "route cancel requires status PLANNED or PUBLISHED")
    if r["committed_stops"] != 0:
        fail("ERR_ROUTE_NOT_EMPTY", "route cancel requires zero committed stops")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(serialize(r), 200)


@bp.route("/coopcare/sitting-routes/<rid>/stops", methods=["POST"])
def add_stop(rid):
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    r = get_route(rid)
    data = body()
    engagement_id = data.get("engagement_id")
    if not isinstance(engagement_id, str) or not engagement_id.strip():
        fail("ERR_INVALID_REQUEST", "engagement_id is required")
    e = store.engagements.get(engagement_id)
    if e is None:
        fail("ERR_ENGAGEMENT_NOT_FOUND", f"Sitting engagement {engagement_id} does not exist")
    planned_start = req_dt(data, "planned_start")
    planned_end = req_dt(data, "planned_end")
    if planned_end <= planned_start:
        fail("ERR_INVALID_TIME_RANGE", "planned_end must be strictly after planned_start")
    expected = data.get("expected_route_version")
    if not is_int(expected):
        fail("ERR_INVALID_REQUEST", "expected_route_version is required and must be an integer")
    # Priority 6: state. Priority 7: OCC. Priority 8: referential fit.
    if r["status"] != "PUBLISHED":
        fail("ERR_ROUTE_NOT_PUBLISHED", "stop add requires route status PUBLISHED")
    if expected != r["version"]:
        fail("ERR_STALE_VERSION", "expected_route_version does not match the current version")
    if e["status"] != "CONFIRMED":
        fail("ERR_ENGAGEMENT_NOT_CONFIRMED", "stop add requires a CONFIRMED engagement")
    eh = store.households[e["household_id"]]
    if eh["zone_code"] != r["zone_code"]:
        fail("ERR_ENGAGEMENT_NOT_CONFIRMED", "engagement household zone does not match the route zone")
    # Priority 10: buffered stop-window collision against PENDING/DONE stops.
    for s in store.stops.values():
        if s["route_id"] != r["id"] or s["status"] not in ("PENDING", "DONE"):
            continue
        if buffered_conflict(planned_start, planned_end, s["planned_start"], s["planned_end"], TRAVEL_BUFFER_MINUTES):
            fail("ERR_STOP_TIME_CONFLICT", "buffered stop window collides with an existing stop on the route")
    # Priority 11: capacity (equality rejects).
    if r["committed_stops"] >= r["max_stops"]:
        fail("ERR_ROUTE_CAPACITY_FULL", "route has reached its stop capacity")
    stop = stamp_new({
        "id": new_id(),
        "route_id": r["id"],
        "engagement_id": engagement_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "sequence": r["committed_stops"] + 1,
        "status": "PENDING",
        "skip_reason": None,
    })
    store.stops[stop["id"]] = stop
    r["committed_stops"] += 1
    touch(r)
    return ok(serialize(stop), 201)


@bp.route("/coopcare/route-stops", methods=["GET"])
def list_stops():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("route_id", "engagement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.stops.values(), filters)


@bp.route("/coopcare/route-stops/<sid>", methods=["GET"])
def read_stop(sid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_stop(sid)), 200)


@bp.route("/coopcare/route-stops/<sid>/complete", methods=["POST"])
def complete_stop(sid):
    uid, role = authenticate()
    require_role(role, {"ServiceTech"})
    s = get_stop(sid)
    route = store.routes[s["route_id"]]
    require_tech(uid, route["technician_id"])
    if s["status"] != "PENDING":
        fail("ERR_STOP_NOT_PENDING", "stop complete requires status PENDING")
    s["status"] = "DONE"
    touch(s)
    return ok(serialize(s), 200)


@bp.route("/coopcare/route-stops/<sid>/skip", methods=["POST"])
def skip_stop(sid):
    uid, role = authenticate()
    require_role(role, {"ServiceTech"})
    s = get_stop(sid)
    route = store.routes[s["route_id"]]
    require_tech(uid, route["technician_id"])
    if s["status"] != "PENDING":
        fail("ERR_STOP_NOT_PENDING", "stop skip requires status PENDING")
    data = body()
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        fail("ERR_INVALID_REQUEST", "reason must be a string")
    s["skip_reason"] = reason
    s["status"] = "SKIPPED"
    # committed_stops deliberately unchanged; SKIPPED stops price at zero in settlement.
    touch(s)
    return ok(serialize(s), 200)
