"""DeliveryRoute endpoints (PRD §3.8)."""
from flask import Blueprint

import clock
import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import domain, serializers

bp = Blueprint("delivery_routes", __name__)


@bp.post("/delivery-routes")
def create_route():
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    body = helpers.get_body()

    region_code = helpers.require_str(body, "region_code")
    service_date_raw = helpers.require_str(body, "service_date")
    try:
        parsed = clock.parse_iso(service_date_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "service_date must be an ISO 8601 timestamp.")
    # Normalize to UTC midnight (date component only).
    normalized = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    service_date = clock.format_iso(normalized)

    shift_start = helpers.require_int(body, "shift_start_minute", minimum=0)
    shift_end = helpers.require_int(body, "shift_end_minute", maximum=1440)
    if not (shift_start < shift_end):
        raise err("ERR_INVALID_REQUEST", "shift_start_minute must be < shift_end_minute.")
    capacity = helpers.require_int(body, "capacity_units", minimum=1)

    rec = {
        "region_code": region_code,
        "service_date": service_date,
        "shift_start_minute": shift_start,
        "shift_end_minute": shift_end,
        "capacity_units": capacity,
        "committed_units": 0,
        "status": "OPEN",
    }
    helpers.stamp_create(rec)
    db.delivery_routes[rec["id"]] = rec
    return response.object_response(serializers.delivery_route(rec), status=201)


@bp.get("/delivery-routes/<rid>")
def get_route(rid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager", "SalesAssociate"})
    rec = helpers.fetch(db.delivery_routes, rid)
    return response.object_response(serializers.delivery_route(rec))


@bp.get("/delivery-routes/<rid>/stops")
def list_route_stops(rid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager", "SalesAssociate"})
    helpers.fetch(db.delivery_routes, rid)
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.stops_for_route(rid), limit, offset)
    return response.array_response(
        [serializers.delivery_stop(s) for s in page], limit, offset, total)


@bp.post("/delivery-routes/<rid>/lock")
def lock_route(rid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    route = helpers.fetch(db.delivery_routes, rid)
    if route["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Route is not OPEN.")
    route["status"] = "LOCKED"
    helpers.touch(route)
    return response.object_response(serializers.delivery_route(route))


@bp.post("/delivery-routes/<rid>/complete")
def complete_route(rid):
    _, role = get_auth()
    require_role(role, {"DeliveryDispatcher", "StoreManager"})
    route = helpers.fetch(db.delivery_routes, rid)
    if route["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Route is not LOCKED.")
    unresolved = [s for s in domain.stops_for_route(rid)
                  if s["status"] not in ("COMPLETED", "CANCELLED")]
    if unresolved:
        raise err("ERR_STOPS_UNRESOLVED", "Route has unresolved stops.")
    route["status"] = "COMPLETED"
    helpers.touch(route)
    return response.object_response(serializers.delivery_route(route))
