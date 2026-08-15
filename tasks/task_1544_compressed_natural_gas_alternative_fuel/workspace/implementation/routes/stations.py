"""Station endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_STATION_NOT_IN_SETUP,
    ERR_STATION_NOT_EQUIPPED,
    ERR_STATION_NOT_ACTIVE,
    ERR_STATION_NOT_SUSPENDED,
    ERR_OVERDUE_INSPECTION,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import station_out
from services.core import (
    recompute_station_posture,
    void_sessions_for_station_suspend,
    station_has_overdue_inspection,
    touch,
)
from validators import (
    body, require_fields, require_string, require_enum, require_positive_int,
    parse_pagination, paginate,
)

bp = Blueprint("stations", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]


def get_station_or_404(station_id: str) -> dict:
    s = STORE.stations.get(station_id)
    if s is None:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    return s


@bp.post("/cng/stations")
def create_station():
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["station_name", "station_code", "access_mode", "backup_capacity_gge"])
    station_name = require_string(data, "station_name")
    station_code = require_string(data, "station_code")
    access_mode = require_enum(data, "access_mode", {"PUBLIC", "PRIVATE", "DUAL"})
    backup_capacity_gge = require_positive_int(data, "backup_capacity_gge")

    now = now_utc()
    station = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_name": station_name,
        "station_code": station_code,
        "access_mode": access_mode,
        "backup_capacity_gge": backup_capacity_gge,
        "uptime_posture": "OUTAGE",
        "status": "SETUP",
    }
    STORE.stations[station["id"]] = station
    return success_object(station_out(station), status=201)


@bp.get("/cng/stations")
def list_stations():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    status_filter = None
    raw = __import__("flask").request.args.get("status")
    if raw is not None:
        status_filter = raw
    items = sorted(STORE.stations.values(), key=lambda s: (s["created_at"], s["id"]))
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([station_out(s) for s in page], limit, offset, total)


@bp.get("/cng/stations/<stationId>")
def get_station(stationId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    station = get_station_or_404(stationId)
    return success_object(station_out(station))


@bp.post("/cng/stations/<stationId>/activate")
def activate_station(stationId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    station = get_station_or_404(stationId)
    if station["status"] != "SETUP":
        raise ApiError(ERR_STATION_NOT_IN_SETUP, 409,
                       "Station activate requires SETUP status")
    has_compressor = any(c["station_id"] == stationId for c in STORE.compressors.values())
    has_dispenser = any(d["station_id"] == stationId for d in STORE.dispensers.values())
    if not (has_compressor and has_dispenser):
        raise ApiError(ERR_STATION_NOT_EQUIPPED, 409,
                       "Station activate requires at least one compressor and one dispenser")
    station["status"] = "ACTIVE"
    touch(station)
    recompute_station_posture(stationId)
    return success_object(station_out(station))


@bp.post("/cng/stations/<stationId>/suspend")
def suspend_station(stationId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    station = get_station_or_404(stationId)
    if station["status"] != "ACTIVE":
        raise ApiError(ERR_STATION_NOT_ACTIVE, 409,
                       "Station suspend requires ACTIVE status")
    station["status"] = "SUSPENDED"
    touch(station)
    void_sessions_for_station_suspend(stationId)
    return success_object(station_out(station))


@bp.post("/cng/stations/<stationId>/resume")
def resume_station(stationId: str):
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    station = get_station_or_404(stationId)
    if station["status"] != "SUSPENDED":
        raise ApiError(ERR_STATION_NOT_SUSPENDED, 409,
                       "Station resume requires SUSPENDED status")
    if station_has_overdue_inspection(stationId):
        raise ApiError(ERR_OVERDUE_INSPECTION, 409,
                       "Station has an OVERDUE safety inspection")
    station["status"] = "ACTIVE"
    touch(station)
    return success_object(station_out(station))
