"""/vehicles endpoints."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_INVALID_INPUT, ERR_NOT_FOUND
from ..serializers import serialize_vehicle
from ..store import store
from ..util import require_json_body, require_str, validate_vin


vehicles_bp = Blueprint("vehicles", __name__)


@vehicles_bp.post("/vehicles")
@require_auth({"CarrierSafetyOfficer"})
def create_vehicle():
    payload = require_json_body()
    vin = require_str(payload, "vin", max_len=32)
    validate_vin(vin)
    carrier_id = require_str(payload, "carrier_id", max_len=128)
    eld_device_id = require_str(payload, "eld_device_id", max_len=128)

    with store.lock:
        # Existence (priority 3).
        if carrier_id not in store.carriers:
            raise ApiError(ERR_NOT_FOUND, 404, "Carrier not found.")
        if eld_device_id not in store.eld_devices:
            raise ApiError(ERR_NOT_FOUND, 404, "ELD device not found.")
        # Uniqueness checks.
        for v in store.vehicles.values():
            if v["vin"] == vin:
                raise ApiError(ERR_INVALID_INPUT, 400, "vin must be unique.")
            if v["eld_device_id"] == eld_device_id:
                raise ApiError(
                    ERR_INVALID_INPUT, 400, "ELD device already paired with another vehicle.",
                )
        entity = {
            "vin": vin,
            "carrier_id": carrier_id,
            "eld_device_id": eld_device_id,
            "current_driver_id": None,
            "odometer_miles": 0,
        }
        store.stamp_create(entity)
        store.vehicles[entity["id"]] = entity
    return ok_object(serialize_vehicle(entity), status=201)


@vehicles_bp.get("/vehicles/<vehicle_id>")
@require_auth({"CarrierSafetyOfficer", "Driver", "FMCSAAuditor"})
def get_vehicle(vehicle_id: str):
    v = store.vehicles.get(vehicle_id)
    if v is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Vehicle not found.")
    return ok_object(serialize_vehicle(v))
