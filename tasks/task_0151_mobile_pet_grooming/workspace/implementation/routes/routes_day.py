"""RouteDay and RouteStop routes."""
from flask import Blueprint, request

import db
import models
import validate as V
from middleware import get_identity, require_role
from errors import err, ERR_VALIDATION, ERR_INVALID_STATE
import lookup
from util import parse_dt
from response import object_response, array_response

bp = Blueprint("route_days", __name__)


@bp.route("/route-days", methods=["POST"])
def create_route_day():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    body = V.require_body(request.get_json(silent=True))
    van_id = V.require_str(body, "van_id")
    service_date = parse_dt(V.require_field(body, "service_date"), "service_date")
    window_start = parse_dt(V.require_field(body, "window_start"), "window_start")
    window_end = parse_dt(V.require_field(body, "window_end"), "window_end")
    coverage_zip = V.require_zip(body, "coverage_zip")
    lookup.get_van(van_id)
    # field-relationship invariant: window_end strictly after window_start
    if not (window_end > window_start):
        raise err(ERR_VALIDATION, "window_end must be strictly after window_start")
    rec = models.base_versioned()
    rec.update({
        "van_id": van_id, "service_date": service_date,
        "window_start": window_start, "window_end": window_end,
        "coverage_zip": coverage_zip, "status": "OPEN", "booked_minutes": 0,
    })
    db.route_days[rec["id"]] = rec
    return object_response(models.ser_route_day(rec), 201)


@bp.route("/route-days/<rid>", methods=["GET"])
def get_route_day(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Groomer"})
    rec = lookup.get_route_day(rid)
    return object_response(models.ser_route_day(rec), 200)


@bp.route("/route-days/<rid>/stops", methods=["GET"])
def list_route_day_stops(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Groomer"})
    rd = lookup.get_route_day(rid)
    limit, offset = V.parse_pagination(request.args)
    items = [s for s in db.route_stops.values() if s["route_day_id"] == rd["id"]]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_route_stop(s) for s in page], limit, offset, total, 200)


@bp.route("/route-days/<rid>/dispatch", methods=["POST"])
def dispatch_route_day(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    rd = lookup.get_route_day(rid)
    if rd["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Route day is not OPEN")
    has_reserved = any(
        s["route_day_id"] == rd["id"] and s["status"] == "RESERVED"
        for s in db.route_stops.values()
    )
    if not has_reserved:
        raise err(ERR_INVALID_STATE, "Route day has no RESERVED stop to dispatch")
    rd["status"] = "LOCKED"
    models.touch(rd)
    return object_response(models.ser_route_day(rd), 200)


@bp.route("/route-days", methods=["GET"])
def list_route_days():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    limit, offset = V.parse_pagination(request.args)
    van_id = request.args.get("van_id")
    items = list(db.route_days.values())
    if van_id:
        items = [r for r in items if r["van_id"] == van_id]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_route_day(r) for r in page], limit, offset, total, 200)


@bp.route("/route-stops/<rid>", methods=["GET"])
def get_route_stop(rid):
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Groomer"})
    rec = lookup.get_route_stop(rid)
    return object_response(models.ser_route_stop(rec), 200)


@bp.route("/route-stops", methods=["GET"])
def list_route_stops():
    _, role = get_identity()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Groomer"})
    limit, offset = V.parse_pagination(request.args)
    route_day_id = request.args.get("route_day_id")
    items = list(db.route_stops.values())
    if route_day_id:
        items = [s for s in items if s["route_day_id"] == route_day_id]
    page, total = V.paginate(items, limit, offset)
    return array_response([models.ser_route_stop(s) for s in page], limit, offset, total, 200)
