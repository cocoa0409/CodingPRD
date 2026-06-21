"""ServiceArea, Crew, Equipment routes."""
from flask import Blueprint, g

import db
import errors
import lookups
import response
from errors import ApiError
from helpers import (as_bool, as_int, as_string, get_json_body, parse_pagination)
from middleware import ALL_ROLES, require_roles
from services import active_bookings_for_resource

bp = Blueprint("resources", __name__)


# ---------------------------------------------------------------------------
# ServiceArea
# ---------------------------------------------------------------------------
@bp.post("/service-areas")
@require_roles("Dispatcher")
def create_service_area():
    body = get_json_body()
    name = as_string(body, "name")
    region_code = as_string(body, "region_code")
    disposal_fee = as_int(body, "disposal_fee_cents_per_ton")
    if disposal_fee < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "disposal_fee_cents_per_ton must be >= 0.")
    requires_permit_authority = as_bool(body, "requires_permit_authority", default=True)
    heritage_pct = body.get("heritage_surcharge_pct", 0.15)
    if heritage_pct is None:
        heritage_pct = 0.15
    if isinstance(heritage_pct, bool) or not isinstance(heritage_pct, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "heritage_surcharge_pct must be a number.")
    if heritage_pct < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "heritage_surcharge_pct must be >= 0.")

    obj = db.stamp_new({
        "name": name,
        "region_code": region_code,
        "disposal_fee_cents_per_ton": disposal_fee,
        "requires_permit_authority": requires_permit_authority,
        "heritage_surcharge_pct": heritage_pct,
    })
    db.service_areas[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/service-areas")
@require_roles(*ALL_ROLES)
def list_service_areas():
    limit, offset = parse_pagination()
    items = db.sort_by_created(db.service_areas.values())
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/service-areas/<sid>")
@require_roles(*ALL_ROLES)
def get_service_area(sid):
    obj = lookups.get_service_area(sid)
    return response.success(db.public(obj), 200)


# ---------------------------------------------------------------------------
# Crew
# ---------------------------------------------------------------------------
@bp.post("/crews")
@require_roles("Dispatcher")
def create_crew():
    body = get_json_body()
    service_area_id = as_string(body, "service_area_id")
    lookups.get_service_area(service_area_id)  # FK existence (404)
    name = as_string(body, "name")
    hourly_rate = as_int(body, "hourly_rate_cents")
    if hourly_rate <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "hourly_rate_cents must be > 0.")
    certified = as_bool(body, "certified_utility_clearance", default=False)

    obj = db.stamp_new({
        "service_area_id": service_area_id,
        "name": name,
        "hourly_rate_cents": hourly_rate,
        "certified_utility_clearance": certified,
        "status": "AVAILABLE",
    })
    db.crews[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/crews")
@require_roles(*ALL_ROLES)
def list_crews():
    from flask import request
    limit, offset = parse_pagination()
    sa_filter = request.args.get("service_area_id")
    items = db.sort_by_created(db.crews.values())
    if sa_filter is not None:
        items = [c for c in items if c["service_area_id"] == sa_filter]
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/crews/<cid>")
@require_roles(*ALL_ROLES)
def get_crew(cid):
    obj = lookups.get_crew(cid)
    return response.success(db.public(obj), 200)


@bp.post("/crews/<cid>/retire")
@require_roles("Dispatcher")
def retire_crew(cid):
    obj = lookups.get_crew(cid)
    if obj["status"] == "RETIRED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Crew already retired.")
    if active_reserved_for_crew(cid):
        raise ApiError(errors.ERR_RESOURCE_HAS_RESERVATIONS, 409,
                       "Crew has a reserved booking.")
    obj["status"] = "RETIRED"
    db.touch(obj)
    return response.success(db.public(obj), 200)


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
@bp.post("/equipment")
@require_roles("Dispatcher")
def create_equipment():
    body = get_json_body()
    service_area_id = as_string(body, "service_area_id")
    lookups.get_service_area(service_area_id)
    if "kind" not in body or body["kind"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: kind.")
    kind = body["kind"]
    if kind not in ("CRANE", "CHIPPER", "STUMP_GRINDER"):
        raise ApiError(errors.ERR_INVALID_ENUM, 400, f"Illegal kind: {kind!r}.")
    name = as_string(body, "name")
    hourly_rate = as_int(body, "hourly_rate_cents")
    if hourly_rate <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "hourly_rate_cents must be > 0.")
    buffer_min = as_int(body, "mobilization_buffer_minutes", required=False, default=30)
    if buffer_min < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "mobilization_buffer_minutes must be >= 0.")

    obj = db.stamp_new({
        "service_area_id": service_area_id,
        "kind": kind,
        "name": name,
        "hourly_rate_cents": hourly_rate,
        "mobilization_buffer_minutes": buffer_min,
        "status": "AVAILABLE",
    })
    db.equipment[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/equipment")
@require_roles(*ALL_ROLES)
def list_equipment():
    from flask import request
    limit, offset = parse_pagination()
    sa_filter = request.args.get("service_area_id")
    items = db.sort_by_created(db.equipment.values())
    if sa_filter is not None:
        items = [e for e in items if e["service_area_id"] == sa_filter]
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/equipment/<eid>")
@require_roles(*ALL_ROLES)
def get_equipment(eid):
    obj = lookups.get_equipment(eid)
    return response.success(db.public(obj), 200)


@bp.post("/equipment/<eid>/retire")
@require_roles("Dispatcher")
def retire_equipment(eid):
    obj = lookups.get_equipment(eid)
    if obj["status"] == "RETIRED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Equipment already retired.")
    if active_reserved_for_equipment(eid):
        raise ApiError(errors.ERR_RESOURCE_HAS_RESERVATIONS, 409,
                       "Equipment has a reserved booking.")
    obj["status"] = "RETIRED"
    db.touch(obj)
    return response.success(db.public(obj), 200)


def active_reserved_for_crew(cid):
    return any(b for b in db.bookings.values()
               if b["resource_kind"] == "CREW" and b["crew_id"] == cid
               and b["status"] == "RESERVED")


def active_reserved_for_equipment(eid):
    return any(b for b in db.bookings.values()
               if b["resource_kind"] == "EQUIPMENT" and b["equipment_id"] == eid
               and b["status"] == "RESERVED")
