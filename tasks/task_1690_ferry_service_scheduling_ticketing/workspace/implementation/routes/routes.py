"""Route endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db, now_iso
from errors import raise_error, ERR_NOT_FOUND, ERR_DUPLICATE
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.serializers import serialize_route, serialize_fare_schedule, serialize_sailing
from services.fare_schedule import evaluate_fare_transitions

bp = Blueprint("routes", __name__)

ALL_ROLES = ("SchedulerAdmin", "TerminalAgent", "CrewPlanner", "Customer")


@bp.post("/ferry/routes")
def create_route():
    require_roles("SchedulerAdmin")
    payload = request.get_json(silent=True) or {}
    route_code = payload.get("route_code")

    # ERR_DUPLICATE: route_code unique
    for r in db.routes.values():
        if r["route_code"] == route_code:
            raise_error(ERR_DUPLICATE, "route_code already in use")

    ts = now_iso()
    route = {
        "id": db.new_id(),
        "route_code": route_code,
        "origin_terminal": payload.get("origin_terminal"),
        "destination_terminal": payload.get("destination_terminal"),
        "crossing_minutes": payload.get("crossing_minutes"),
        "turnaround_minutes": payload.get("turnaround_minutes"),
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.routes[route["id"]] = route
    return success_object(serialize_route(route), status=201)


@bp.get("/ferry/routes/<route_id>")
def get_route(route_id):
    require_roles(*ALL_ROLES)
    route = db.routes.get(route_id)
    if route is None:
        raise_error(ERR_NOT_FOUND, "Route not found")
    return success_object(serialize_route(route))


@bp.get("/ferry/routes")
def list_routes():
    require_roles(*ALL_ROLES)
    status = request.args.get("status")
    items = [r for r in db.routes.values() if status is None or r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_route(r) for r in page], meta)


@bp.get("/ferry/routes/<route_id>/fare-schedules")
def list_route_fare_schedules(route_id):
    require_roles(*ALL_ROLES)
    route = db.routes.get(route_id)
    if route is None:
        raise_error(ERR_NOT_FOUND, "Route not found")
    evaluate_fare_transitions()  # lazy evaluation on read (§2.4)
    season = request.args.get("season")
    status = request.args.get("status")
    items = [f for f in db.fare_schedules.values()
             if f["route_id"] == route_id
             and (season is None or f["season"] == season)
             and (status is None or f["status"] == status)]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_fare_schedule(f) for f in page], meta)


@bp.get("/ferry/routes/<route_id>/sailings")
def list_route_sailings(route_id):
    require_roles(*ALL_ROLES)
    route = db.routes.get(route_id)
    if route is None:
        raise_error(ERR_NOT_FOUND, "Route not found")
    status = request.args.get("status")
    season = request.args.get("season")
    items = [s for s in db.sailings.values()
             if s["route_id"] == route_id
             and (status is None or s["status"] == status)
             and (season is None or s["season"] == season)]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_sailing(s) for s in page], meta)
