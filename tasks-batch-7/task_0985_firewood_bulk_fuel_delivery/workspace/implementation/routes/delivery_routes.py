"""Delivery route endpoints (PRD §3.4)."""

from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_route
from util import (
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_field,
    require_number,
    require_str,
)

bp = Blueprint("delivery_routes", __name__)


@bp.post("/api/v1/delivery-routes")
def create_route():
    require_roles("RoutePlanner", "OperationsManager")
    body = get_json_body()
    route_code = require_str(body, "route_code")
    depot_name = require_str(body, "depot_name")
    prefixes = require_field(body, "service_postal_prefixes")
    if not isinstance(prefixes, list):
        raise errors.validation("service_postal_prefixes must be an array")
    capacity = require_number(body, "capacity_cord_equivalent")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise errors.validation("active must be a boolean")
    ts = now_iso()
    rid = new_id()
    route = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "route_code": route_code,
        "depot_name": depot_name,
        "service_postal_prefixes": prefixes,
        "capacity_cord_equivalent": capacity,
        "active": active,
    }
    db.delivery_routes[rid] = route
    return success_object(serialize_route(route), status=201)


def _get_route_or_404(rid):
    r = db.delivery_routes.get(rid)
    if not r:
        raise errors.not_found(f"DeliveryRoute {rid} not found")
    return r


@bp.get("/api/v1/delivery-routes/<rid>")
def get_route(rid):
    require_roles("RoutePlanner", "OperationsManager", "CustomerService", "Driver")
    return success_object(serialize_route(_get_route_or_404(rid)))


@bp.get("/api/v1/delivery-routes")
def list_routes():
    require_roles("RoutePlanner", "OperationsManager", "CustomerService", "Driver")
    limit, offset = parse_pagination()
    items = list(db.delivery_routes.values())
    a = request.args.get("active")
    if a is not None:
        aval = a.lower() in ("true", "1", "yes")
        items = [r for r in items if r.get("active", True) == aval]
    pc = request.args.get("postal_code")
    if pc is not None:
        items = [
            r for r in items
            if any(pc.startswith(p) for p in r.get("service_postal_prefixes", []))
        ]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_route(r) for r in page], total, limit, offset)
