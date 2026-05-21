"""/drivers — create, fetch, bind, unbind."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_CROSS_CARRIER_BIND,
    ERR_DRIVER_ALREADY_BOUND,
    ERR_ELD_NOT_CERTIFIED,
    ERR_INVALID_DUTY_STATUS_FOR_BIND,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    ERR_VEHICLE_ALREADY_BOUND,
)
from ..serializers import serialize_driver
from ..store import store
from ..util import (
    optional_str,
    require_enum,
    require_json_body,
    require_str,
    validate_cdl_number,
)


drivers_bp = Blueprint("drivers", __name__)


@drivers_bp.post("/drivers")
@require_auth({"CarrierSafetyOfficer"})
def create_driver():
    payload = require_json_body()
    cdl_number = require_str(payload, "cdl_number", max_len=32)
    validate_cdl_number(cdl_number)
    full_name = require_str(payload, "full_name", max_len=256)
    carrier_id = require_str(payload, "carrier_id", max_len=128)
    cycle_type = payload.get("cycle_type") or "SEVENTY_HOUR_EIGHT_DAY"
    if cycle_type not in {"SEVENTY_HOUR_EIGHT_DAY", "SIXTY_HOUR_SEVEN_DAY"}:
        raise ApiError(ERR_INVALID_INPUT, 400, "cycle_type invalid.")
    home_tz = payload.get("home_terminal_timezone") or "America/New_York"
    if not isinstance(home_tz, str):
        raise ApiError(ERR_INVALID_INPUT, 400, "home_terminal_timezone must be a string.")

    with store.lock:
        if carrier_id not in store.carriers:
            raise ApiError(ERR_NOT_FOUND, 404, "Carrier not found.")
        for d in store.drivers.values():
            if d["cdl_number"] == cdl_number:
                raise ApiError(ERR_INVALID_INPUT, 400, "cdl_number must be unique.")
        entity = {
            "cdl_number": cdl_number,
            "full_name": full_name,
            "carrier_id": carrier_id,
            "cycle_type": cycle_type,
            "duty_status": "OFF_DUTY",
            "bound_vehicle_id": None,
            "bound_eld_device_id": None,
            "home_terminal_timezone": home_tz,
            "last_34_hour_restart_completed_at": None,
        }
        store.stamp_create(entity)
        store.drivers[entity["id"]] = entity
    return ok_object(serialize_driver(entity), status=201)


@drivers_bp.get("/drivers/<driver_id>")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_driver(driver_id: str):
    d = store.drivers.get(driver_id)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
    return ok_object(serialize_driver(d))


@drivers_bp.post("/drivers/<driver_id>/bind")
@require_auth({"Driver"})
def bind_driver(driver_id: str):
    payload = require_json_body()
    vehicle_id = require_str(payload, "vehicle_id", max_len=128)

    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        vehicle = store.vehicles.get(vehicle_id)
        if vehicle is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Vehicle not found.")
        device = store.eld_devices.get(vehicle.get("eld_device_id"))
        if device is None:
            raise ApiError(ERR_NOT_FOUND, 404, "ELD device for vehicle not found.")

        # Validation priorities 14-18.
        if not device.get("certified_for_fmcsa", True):
            raise ApiError(ERR_ELD_NOT_CERTIFIED, 422, "Vehicle's ELD device is not FMCSA-certified.")
        if vehicle.get("carrier_id") != driver.get("carrier_id"):
            raise ApiError(ERR_CROSS_CARRIER_BIND, 422, "Vehicle and driver belong to different carriers.")
        if driver.get("duty_status") != "OFF_DUTY":
            raise ApiError(
                ERR_INVALID_DUTY_STATUS_FOR_BIND,
                409,
                "Driver must be OFF_DUTY to bind to a vehicle.",
            )
        if vehicle.get("current_driver_id") is not None:
            raise ApiError(ERR_VEHICLE_ALREADY_BOUND, 409, "Vehicle is already bound to another driver.")
        if driver.get("bound_vehicle_id") is not None:
            raise ApiError(ERR_DRIVER_ALREADY_BOUND, 409, "Driver is already bound to another vehicle.")

        # Atomic update.
        driver["bound_vehicle_id"] = vehicle["id"]
        driver["bound_eld_device_id"] = vehicle["eld_device_id"]
        vehicle["current_driver_id"] = driver["id"]
        store.bump(driver)
        store.bump(vehicle)

    return ok_object(serialize_driver(driver))


@drivers_bp.post("/drivers/<driver_id>/unbind")
@require_auth({"Driver"})
def unbind_driver(driver_id: str):
    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        if driver.get("duty_status") not in ("OFF_DUTY", "SLEEPER_BERTH"):
            raise ApiError(
                ERR_INVALID_DUTY_STATUS_FOR_BIND,
                409,
                "Driver must be OFF_DUTY or SLEEPER_BERTH to unbind.",
            )
        veh_id = driver.get("bound_vehicle_id")
        if veh_id:
            veh = store.vehicles.get(veh_id)
            if veh is not None:
                veh["current_driver_id"] = None
                store.bump(veh)
        driver["bound_vehicle_id"] = None
        driver["bound_eld_device_id"] = None
        store.bump(driver)
    return ok_object(serialize_driver(driver))
