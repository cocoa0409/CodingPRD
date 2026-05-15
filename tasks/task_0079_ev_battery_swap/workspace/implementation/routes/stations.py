"""Station and ChargingSlot routes."""

from flask import Blueprint, request

from db import DB, new_id
from errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_INPUT,
    raise_error,
)
from middleware import auth_required
from response import list_response, success_response
from services.common import (
    get_body,
    get_or_404,
    get_pagination,
    init_common,
    optional_enum,
    optional_string,
    paginate,
    require_enum,
    require_int,
    require_number,
    require_string,
    sort_by_created_at_asc,
)


bp = Blueprint("stations", __name__, url_prefix="/swap-stations")


CHARGING_SLOT_STATUSES = {"EMPTY", "OCCUPIED", "OUT_OF_SERVICE"}
TOU_ZONES = {"PEAK", "SHOULDER", "OFF_PEAK"}
STATION_STATUSES = {"OPEN", "RESTRICTED", "OFFLINE"}


# ---- Station -----------------------------------------------------------------

@bp.route("/stations", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_station():
    body = get_body()
    name = require_string(body, "name", min_len=1, max_len=120)
    latitude = require_number(body, "latitude")
    longitude = require_number(body, "longitude")
    if latitude < -90.0 or latitude > 90.0:
        raise_error(ERR_INVALID_INPUT, "latitude must be in [-90, 90]")
    if longitude < -180.0 or longitude > 180.0:
        raise_error(ERR_INVALID_INPUT, "longitude must be in [-180, 180]")
    total_slots = require_int(body, "total_slots", min_value=1, max_value=64)

    for s in DB["stations"].values():
        if s.get("name") == name:
            raise_error(ERR_DUPLICATE_RESOURCE, "Station name already exists")

    row = {
        "id": new_id(),
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "total_slots": int(total_slots),
        "status": "OPEN",
        "idle_battery_count": 0,
        "charging_battery_count": 0,
    }
    init_common(row)
    DB["stations"][row["id"]] = row
    return success_response(row, http_status=201)


@bp.route("/stations", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator", "Member"])
def list_stations():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in STATION_STATUSES:
        raise_error(ERR_INVALID_INPUT, "Unknown status filter")

    items = list(DB["stations"].values())
    if status_filter is not None:
        items = [s for s in items if s.get("status") == status_filter]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)


@bp.route("/stations/<station_id>", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator", "Member"])
def get_station(station_id):
    row = get_or_404("stations", station_id)
    return success_response(row)


# ---- ChargingSlot ------------------------------------------------------------

@bp.route("/stations/<station_id>/charging-slots", methods=["POST"])
@auth_required(["PlatformAdmin"])
def add_charging_slot(station_id):
    station = get_or_404("stations", station_id)
    body = get_body()
    slot_number = require_int(body, "slot_number", min_value=1, max_value=int(station["total_slots"]))
    tou_zone = optional_enum(body, "tou_zone", TOU_ZONES, default="SHOULDER")

    # uniqueness per station
    for slot in DB["charging_slots"].values():
        if (slot.get("station_id") == station_id
                and int(slot.get("slot_number", -1)) == slot_number):
            raise_error(ERR_DUPLICATE_RESOURCE,
                        f"slot_number {slot_number} already exists at this station")

    row = {
        "id": new_id(),
        "station_id": station_id,
        "slot_number": slot_number,
        "status": "EMPTY",
        "battery_id": None,
        "tou_zone": tou_zone,
    }
    init_common(row)
    DB["charging_slots"][row["id"]] = row
    return success_response(row, http_status=201)


@bp.route("/stations/<station_id>/charging-slots", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator"])
def list_charging_slots(station_id):
    get_or_404("stations", station_id)
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in CHARGING_SLOT_STATUSES:
        raise_error(ERR_INVALID_INPUT, "Unknown slot status filter")

    items = [s for s in DB["charging_slots"].values() if s.get("station_id") == station_id]
    if status_filter is not None:
        items = [s for s in items if s.get("status") == status_filter]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)
