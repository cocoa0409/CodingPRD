from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields, bump
from envelope import success, created
from errors import APIError, ERR_INVALID_INPUT, ERR_NOT_FOUND, ERR_PRICING_NOT_CONFIGURED
from validation import need_body, require_str, require_enum, require_timestamp, occ_check
from serializers import serialize_cabinet, serialize_slot
from services.cabinet_state import recompute_online_status

bp = Blueprint("cabinets", __name__)

VALID_MODELS = {"SLOT_8", "SLOT_16", "SLOT_24"}
SLOT_COUNT_BY_MODEL = {"SLOT_8": 8, "SLOT_16": 16, "SLOT_24": 24}
VALID_CITIES = {"BJ", "SH"}


@bp.post("/cabinets")
def create_cabinet():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))

    cabinet_code = require_str(body, "cabinet_code")
    city_code = require_enum(body, "city_code", VALID_CITIES)
    location_partner_id = require_str(body, "location_partner_id")
    model = require_enum(body, "model", VALID_MODELS)
    firmware_version = require_str(body, "firmware_version")

    cf = make_common_fields()
    cabinet = {
        **cf,
        "cabinet_code": cabinet_code,
        "city_code": city_code,
        "location_partner_id": location_partner_id,
        "model": model,
        "total_slots": SLOT_COUNT_BY_MODEL[model],
        "firmware_version": firmware_version,
        "online_status": "ONLINE",
        "last_heartbeat_at": cf["created_at"],
    }
    db.cabinets[cabinet["id"]] = cabinet

    for idx in range(cabinet["total_slots"]):
        scf = make_common_fields()
        slot = {
            **scf,
            "cabinet_id": cabinet["id"],
            "slot_index": idx,
            "device_id": None,
            "slot_status": "EMPTY",
        }
        db.slots[slot["id"]] = slot

    return created(serialize_cabinet(cabinet))


@bp.get("/cabinets/<cabinet_id>")
def get_cabinet(cabinet_id):
    require_role({"Admin", "Operator"})
    cab = db.cabinets.get(cabinet_id)
    if cab is None:
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")
    recompute_online_status(cab)
    return success(serialize_cabinet(cab))


@bp.post("/cabinets/<cabinet_id>/heartbeat")
def heartbeat(cabinet_id):
    require_role({"Admin"})
    cab = db.cabinets.get(cabinet_id)
    if cab is None:
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")
    body = need_body(request.get_json(silent=True))
    timestamp = require_timestamp(body, "timestamp")
    firmware_version = body.get("firmware_version")
    if firmware_version is not None and not isinstance(firmware_version, str):
        raise APIError(ERR_INVALID_INPUT, 400, "Field 'firmware_version' must be a string")
    occ_check(cab, body)

    cab["last_heartbeat_at"] = timestamp
    if firmware_version is not None:
        cab["firmware_version"] = firmware_version
    recompute_online_status(cab)
    bump(cab)
    return success(serialize_cabinet(cab))


@bp.post("/cabinets/<cabinet_id>/slots/<slot_index>/eject")
def eject_slot(cabinet_id, slot_index):
    require_role({"Operator"})
    cab = db.cabinets.get(cabinet_id)
    if cab is None:
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")
    try:
        idx = int(slot_index)
    except (ValueError, TypeError):
        raise APIError(ERR_NOT_FOUND, 404, "Slot not found")

    slot = None
    for s in db.slots.values():
        if s["cabinet_id"] == cabinet_id and s["slot_index"] == idx:
            slot = s
            break
    if slot is None:
        raise APIError(ERR_NOT_FOUND, 404, "Slot not found")

    body = request.get_json(silent=True) or {}
    if body:
        occ_check(slot, body)

    from errors import ERR_INVALID_STATE
    if slot["slot_status"] != "STUCK":
        raise APIError(ERR_INVALID_STATE, 409, "Slot is not STUCK")

    # STUCK → EMPTY; if there is a housed device with status STUCK_IN_SLOT, it returns to AVAILABLE.
    device = None
    if slot.get("device_id"):
        device = db.devices.get(slot["device_id"])
    slot["slot_status"] = "EMPTY"
    slot["device_id"] = None
    bump(slot)

    if device is not None and device["status"] == "STUCK_IN_SLOT":
        device["status"] = "AVAILABLE"
        device["current_cabinet_id"] = None
        device["current_slot_index"] = None
        bump(device)

    # Note: the rental remains STUCK; user must call return-retry to close the cycle.
    return success(serialize_slot(slot))
