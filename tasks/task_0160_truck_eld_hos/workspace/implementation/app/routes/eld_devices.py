"""/eld-devices endpoints."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_INVALID_INPUT, ERR_NOT_FOUND
from ..serializers import serialize_eld_device
from ..store import store
from ..util import require_bool, require_json_body, require_str, validate_serial_number


eld_devices_bp = Blueprint("eld_devices", __name__)


@eld_devices_bp.post("/eld-devices")
@require_auth({"PlatformAdmin"})
def create_device():
    payload = require_json_body()
    serial_number = require_str(payload, "serial_number", max_len=64)
    validate_serial_number(serial_number)
    firmware_version = require_str(payload, "firmware_version", max_len=64)
    certified = require_bool(payload, "certified_for_fmcsa", default=True)

    with store.lock:
        for d in store.eld_devices.values():
            if d["serial_number"] == serial_number:
                raise ApiError(ERR_INVALID_INPUT, 400, "serial_number must be unique.")
        entity = {
            "serial_number": serial_number,
            "firmware_version": firmware_version,
            "certified_for_fmcsa": bool(certified) if certified is not None else True,
        }
        store.stamp_create(entity)
        store.eld_devices[entity["id"]] = entity
    return ok_object(serialize_eld_device(entity), status=201)


@eld_devices_bp.get("/eld-devices/<device_id>")
@require_auth({"PlatformAdmin", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_device(device_id: str):
    d = store.eld_devices.get(device_id)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ELD device not found.")
    return ok_object(serialize_eld_device(d))
