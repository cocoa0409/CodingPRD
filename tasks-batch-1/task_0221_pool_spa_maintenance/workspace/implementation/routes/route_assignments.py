"""RouteAssignment endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_int,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.lookup import get_route_or_404

bp = Blueprint("routes", __name__)


@bp.post("/routes")
@require_roles("RouteManager")
def create_route():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        technician_id = require_str(body, "technician_id")
        service_date = require_str(body, "service_date")
        window_start = require_int(body, "window_start_minute", minimum=0, maximum=1439)
        window_end = require_int(body, "window_end_minute", minimum=1, maximum=1440)
        capacity_visits = require_int(body, "capacity_visits", minimum=1)
        # Interval validity (priority 7): window_end must exceed window_start.
        if window_end <= window_start:
            raise err("ERR_INVALID_INTERVAL", "window_end_minute must exceed window_start_minute")
        rec = new_record(
            {
                "technician_id": technician_id,
                "service_date": service_date,
                "window_start_minute": window_start,
                "window_end_minute": window_end,
                "capacity_visits": capacity_visits,
                "status": "PLANNED",
            }
        )
        db.routes[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/routes/<route_id>")
@require_roles("RouteManager", "FieldTechnician")
def get_route(route_id):
    with db.lock:
        route = get_route_or_404(route_id)
        return success(serialize(route), 200)


@bp.get("/routes")
@require_roles("RouteManager", "FieldTechnician")
def list_routes():
    with db.lock:
        limit, offset = paginate(request.args)
        technician_id = request.args.get("technician_id")
        items = list(db.routes.values())
        if technician_id is not None:
            items = [r for r in items if r["technician_id"] == technician_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/routes/<route_id>/visits")
@require_roles("RouteManager", "FieldTechnician")
def list_route_visits(route_id):
    with db.lock:
        get_route_or_404(route_id)
        limit, offset = paginate(request.args)
        items = [v for v in db.visits.values() if v["route_id"] == route_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        from routes.visits import serialize_visit

        return success_list([serialize_visit(v) for v in page], limit, offset, total)


@bp.post("/routes/<route_id>/dispatch")
@require_roles("RouteManager")
def dispatch_route(route_id):
    with db.lock:
        route = get_route_or_404(route_id)
        if route["status"] != "PLANNED":
            raise err("ERR_INVALID_STATE", "Route cannot be dispatched from its current state")
        # Must hold at least one SCHEDULED visit (priority 11).
        has_scheduled = any(
            v["route_id"] == route_id and v["status"] == "SCHEDULED"
            for v in db.visits.values()
        )
        if not has_scheduled:
            raise err("ERR_EMPTY_ROUTE", "Route has no scheduled visit to dispatch")
        route["status"] = "DISPATCHED"
        touch(route)
        return success(serialize(route), 200)


@bp.post("/routes/<route_id>/close")
@require_roles("RouteManager")
def close_route(route_id):
    with db.lock:
        route = get_route_or_404(route_id)
        if route["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE", "Route cannot be closed from its current state")
        # No visit left SCHEDULED or RECOVERY_SCHEDULED.
        has_open = any(
            v["route_id"] == route_id and v["status"] in ("SCHEDULED", "RECOVERY_SCHEDULED")
            for v in db.visits.values()
        )
        if has_open:
            raise err("ERR_INVALID_STATE", "Route still has open visits")
        route["status"] = "CLOSED"
        touch(route)
        return success(serialize(route), 200)
