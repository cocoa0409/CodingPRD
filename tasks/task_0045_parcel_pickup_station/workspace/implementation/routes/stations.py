"""Station, ShelfZone, Staff routes."""
from flask import Blueprint, request
from response import ok_object, ok_array
from middleware import require_roles
from services.common import parse_pagination, sort_by_created
from services.station import (
    create_station, get_station, update_station,
    create_staff, get_staff, update_staff,
)
from services.shelf_zone import create_zone, list_zones_for_station
from services.serialize import station as ser_station, shelf_zone as ser_zone, staff as ser_staff
from db import store


bp = Blueprint("stations", __name__)


@bp.post("/stations")
@require_roles("PlatformAdmin")
def post_station():
    body = request.get_json(silent=True, force=True) or {}
    s = create_station(body)
    return ok_object(ser_station(s), status=201)


@bp.get("/stations")
@require_roles("PlatformAdmin", "Manager", "Clerk")
def list_stations():
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = list(store.stations.values())
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_station(i) for i in page], limit, offset, total)


@bp.get("/stations/<station_id>")
@require_roles("PlatformAdmin", "Manager", "Clerk")
def read_station(station_id):
    s = get_station(station_id)
    return ok_object(ser_station(s))


@bp.patch("/stations/<station_id>")
@require_roles("PlatformAdmin", "Manager")
def patch_station(station_id):
    body = request.get_json(silent=True, force=True) or {}
    s = update_station(station_id, body)
    return ok_object(ser_station(s))


@bp.post("/stations/<station_id>/shelf-zones")
@require_roles("Manager")
def post_shelf_zone(station_id):
    body = request.get_json(silent=True, force=True) or {}
    z = create_zone(station_id, body)
    return ok_object(ser_zone(z), status=201)


@bp.get("/stations/<station_id>/shelf-zones")
@require_roles("Manager", "Clerk")
def list_shelf_zones(station_id):
    get_station(station_id)
    limit, offset = parse_pagination(request.args)
    items = sort_by_created(list_zones_for_station(station_id))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_zone(i) for i in page], limit, offset, total)


@bp.post("/stations/<station_id>/staff")
@require_roles("Manager")
def post_staff(station_id):
    body = request.get_json(silent=True, force=True) or {}
    s = create_staff(station_id, body)
    return ok_object(ser_staff(s), status=201)


@bp.patch("/staff/<staff_id>")
@require_roles("Manager")
def patch_staff(staff_id):
    body = request.get_json(silent=True, force=True) or {}
    s = update_staff(staff_id, body)
    return ok_object(ser_staff(s))
