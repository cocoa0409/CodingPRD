"""Vehicle routes."""

from flask import Blueprint

from db import DB, new_id
from errors import ERR_DUPLICATE_RESOURCE, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.common import (
    bump_version,
    get_body,
    get_or_404,
    init_common,
    optional_string,
    require_string,
)
from services.lookups import vehicle_model_by_code


bp = Blueprint("vehicles", __name__, url_prefix="/swap-stations")


@bp.route("/vehicles", methods=["POST"])
@auth_required(["Member", "PlatformAdmin"])
def create_vehicle():
    body = get_body()
    vin = require_string(body, "vin", min_len=11, max_len=17)
    vehicle_model_code = require_string(body, "vehicle_model_code")
    owner_member_id = require_string(body, "owner_member_id")
    installed_battery_id = optional_string(body, "installed_battery_id")

    if vehicle_model_by_code(vehicle_model_code) is None:
        raise_error(ERR_INVALID_INPUT, "vehicle_model_code does not exist")
    if DB["members"].get(owner_member_id) is None:
        raise_error(ERR_INVALID_INPUT, "owner_member_id does not exist")
    if installed_battery_id is not None:
        if DB["batteries"].get(installed_battery_id) is None:
            raise_error(ERR_INVALID_INPUT, "installed_battery_id does not exist")

    for v in DB["vehicles"].values():
        if v.get("vin") == vin:
            raise_error(ERR_DUPLICATE_RESOURCE, "Vehicle vin already exists")

    row = {
        "id": new_id(),
        "vin": vin,
        "vehicle_model_code": vehicle_model_code,
        "owner_member_id": owner_member_id,
        "installed_battery_id": installed_battery_id,
    }
    init_common(row)
    DB["vehicles"][row["id"]] = row

    # If the vehicle arrives with a pack already fitted, that pack must
    # be IN_USE so the swap-workflow uninstall step finds it in the
    # state required by PRD §3.4 ("outgoing battery — whose status was
    # IN_USE — transitions to IDLE"). The host station's
    # idle_battery_count is decremented accordingly because the battery
    # is leaving station inventory and is now installed in the vehicle.
    if installed_battery_id is not None:
        battery = DB["batteries"].get(installed_battery_id)
        if battery is not None and battery.get("status") == "IDLE":
            prev = battery["status"]
            battery["status"] = "IN_USE"
            station = DB["stations"].get(battery.get("station_id"))
            if station is not None:
                station["idle_battery_count"] = max(
                    0, int(station.get("idle_battery_count", 0)) - 1
                )
                bump_version(station)
            bump_version(battery)
            append_audit(
                "BATTERY_STATUS_CHANGE", "Battery",
                installed_battery_id, prev, "IN_USE",
            )
    return success_response(row, http_status=201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
@auth_required(["Member", "PlatformAdmin", "StationOperator"])
def get_vehicle(vehicle_id):
    row = get_or_404("vehicles", vehicle_id)
    return success_response(row)
