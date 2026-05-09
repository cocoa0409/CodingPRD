from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields, bump
from envelope import success, created
from errors import APIError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_INVALID_INPUT
from validation import need_body, require_str, require_enum, require_int, occ_check
from serializers import serialize_device, serialize_repair_ticket
from services.cascade import create_repair_ticket

bp = Blueprint("devices", __name__)

VALID_DEVICE_MODELS = {"PB_5K", "PB_10K", "PB_20K"}
VALID_ISSUE_CODES = {"ABNORMAL_BATTERY", "CHARGING_FAILURE", "PHYSICAL_DAMAGE", "STUCK_DEVICE", "OFFLINE_CABINET"}


@bp.post("/devices")
def create_device():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))

    device_code = require_str(body, "device_code")
    model = require_enum(body, "model", VALID_DEVICE_MODELS)
    battery_level = require_int(body, "battery_level", min_value=0, max_value=100)
    current_cabinet_id = require_str(body, "current_cabinet_id")
    current_slot_index = require_int(body, "current_slot_index", min_value=0)

    cab = db.cabinets.get(current_cabinet_id)
    if cab is None:
        raise APIError(ERR_NOT_FOUND, 404, "Cabinet not found")

    target_slot = None
    for s in db.slots.values():
        if s["cabinet_id"] == current_cabinet_id and s["slot_index"] == current_slot_index:
            target_slot = s
            break
    if target_slot is None:
        raise APIError(ERR_NOT_FOUND, 404, "Slot not found")
    if target_slot["slot_status"] != "EMPTY":
        raise APIError(ERR_INVALID_STATE, 409, "Slot is not EMPTY")

    cf = make_common_fields()
    device = {
        **cf,
        "device_code": device_code,
        "model": model,
        "battery_level": battery_level,
        "status": "AVAILABLE",
        "current_cabinet_id": current_cabinet_id,
        "current_slot_index": current_slot_index,
    }
    db.devices[device["id"]] = device

    target_slot["device_id"] = device["id"]
    target_slot["slot_status"] = "OCCUPIED"
    bump(target_slot)

    return created(serialize_device(device))


@bp.get("/devices/<device_id>")
def get_device(device_id):
    require_role({"Admin", "Operator"})
    d = db.devices.get(device_id)
    if d is None:
        raise APIError(ERR_NOT_FOUND, 404, "Device not found")
    return success(serialize_device(d))


@bp.post("/devices/<device_id>/report-fault")
def report_fault(device_id):
    uid, _ = require_role({"User"})
    device = db.devices.get(device_id)
    if device is None:
        raise APIError(ERR_NOT_FOUND, 404, "Device not found")

    body = need_body(request.get_json(silent=True))
    issue_code = require_enum(body, "issue_code", VALID_ISSUE_CODES)
    occ_check(device, body)

    # Caller must be the holder: there must exist a Rental with user_id==X-User-ID,
    # device_id==device_id, and rental_status IN {ACTIVE, OVERDUE, STUCK}.
    holder_rental = None
    for r in db.rentals.values():
        if r["user_id"] == uid and r["device_id"] == device_id and r["rental_status"] in {"ACTIVE", "OVERDUE", "STUCK"}:
            holder_rental = r
            break
    if holder_rental is None:
        raise APIError(ERR_FORBIDDEN, 403, "Caller is not the device holder")

    # If device is BORROWED at the moment of report, status remains untouched.
    # Otherwise (AVAILABLE), the create_repair_ticket cascade handles the device→FAULTY chain.
    ticket = create_repair_ticket(
        target_type="DEVICE",
        target_id=device_id,
        source="USER_REPORTED",
        issue_code=issue_code,
    )
    return success(serialize_repair_ticket(ticket))
