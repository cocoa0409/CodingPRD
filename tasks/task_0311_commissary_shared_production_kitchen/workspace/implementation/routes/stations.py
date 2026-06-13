"""Station provisioning, update, and listing."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import get_identity, require_roles, get_json_body, parse_pagination
from response import success, paginated
from services.common import (
    stamp_new, touch, public, get_or_404, sorted_by_creation, paginate,
    require_fields, as_int,
)

bp = Blueprint("stations", __name__)

STATION_CLASSES = {"PREP_TABLE", "CONVECTION_OVEN", "BLAST_CHILLER"}
STATION_STATUSES = {"OPEN", "OUT_OF_SERVICE"}


@bp.post("/stations")
def create_station():
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    require_fields(body, ["name", "station_class"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError("ERR_INVALID_REQUEST")
    if body["station_class"] not in STATION_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST")
    turnover = 30
    if "turnover_buffer_minutes" in body and body["turnover_buffer_minutes"] is not None:
        turnover = as_int(body["turnover_buffer_minutes"])
        if turnover < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    status = body.get("status", "OPEN")
    if status not in STATION_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST")
    with LOCK:
        station = {
            "name": body["name"],
            "station_class": body["station_class"],
            "turnover_buffer_minutes": turnover,
            "status": status,
        }
        stamp_new(station)
        db.stations[station["id"]] = station
        return success(public(station), 201)


@bp.get("/stations")
def list_stations():
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    station_class = request.args.get("station_class")
    status = request.args.get("status")
    with LOCK:
        records = sorted_by_creation(list(db.stations.values()))
        if station_class:
            records = [s for s in records if s["station_class"] == station_class]
        if status:
            records = [s for s in records if s["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/stations/<station_id>")
def get_station(station_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        station = get_or_404(db.stations, station_id)
        return success(public(station))


@bp.patch("/stations/<station_id>")
def update_station(station_id):
    _, role = get_identity()
    require_roles(role, {"FacilityManager"})
    body = get_json_body()
    with LOCK:
        station = get_or_404(db.stations, station_id)
        changed = False
        if "status" in body and body["status"] is not None:
            if body["status"] not in STATION_STATUSES:
                raise ApiError("ERR_INVALID_REQUEST")
            station["status"] = body["status"]
            changed = True
        if "turnover_buffer_minutes" in body and body["turnover_buffer_minutes"] is not None:
            turnover = as_int(body["turnover_buffer_minutes"])
            if turnover < 0:
                raise ApiError("ERR_INVALID_REQUEST")
            station["turnover_buffer_minutes"] = turnover
            changed = True
        if changed:
            touch(station)
        return success(public(station))


@bp.get("/stations/<station_id>/bookings")
def list_station_bookings(station_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        get_or_404(db.stations, station_id)
        records = [b for b in db.bookings.values() if b["station_id"] == station_id]
        records = sorted_by_creation(records)
        if status:
            records = [b for b in records if b["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)
