"""Appointment slots: create, close, reads."""
from flask import Blueprint, request

import db
import errors
import lookup
from common import (
    get_json_body,
    paginate,
    require_enum,
    require_integer,
    require_iso_datetime,
    require_string,
)
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from services.serialize import serialize_slot
from timeutil import iso_to_epoch

bp = Blueprint("slots", __name__)

DONATION_TYPES = {"WHOLE", "PLASMA", "PLATELET"}


def recompute_slot_status(slot):
    """OPEN/FULL derived from booked_count vs capacity. CLOSED is sticky
    (only the close action sets it; it is not auto-cleared here)."""
    if slot["status"] == "CLOSED":
        return
    if slot["booked_count"] >= slot["capacity"]:
        slot["status"] = "FULL"
    else:
        slot["status"] = "OPEN"


@bp.route("/blood-bank/slots", methods=["POST"])
@require_roles("CenterAdmin")
def create_slot():
    body = get_json_body()
    with db.lock:
        center_id = require_string(body, "center_id")
        donation_type = require_enum(body, "donation_type", DONATION_TYPES)
        starts_at = require_iso_datetime(body, "starts_at")
        ends_at = require_iso_datetime(body, "ends_at")
        capacity = require_integer(body, "capacity", minimum=1)
        center = lookup.center(center_id)
        # window validity (422)
        if iso_to_epoch(ends_at) <= iso_to_epoch(starts_at):
            raise ApiError(errors.ERR_INVALID_SLOT_WINDOW, 422,
                           "ends_at must be strictly after starts_at.")
        slot = {
            "center_id": center_id,
            "donation_type": donation_type,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "capacity": capacity,
            "booked_count": 0,
            "status": "OPEN",
        }
        db.stamp_new(slot)
        db.slots[slot["id"]] = slot
        return success(serialize_slot(slot), status=201)


@bp.route("/blood-bank/slots", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "InventoryManager", "Donor")
def list_slots():
    center_id = request.args.get("center_id")
    donation_type = request.args.get("donation_type")
    status = request.args.get("status")
    with db.lock:
        rows = list(db.slots.values())
        if center_id is not None:
            rows = [s for s in rows if s["center_id"] == center_id]
        if donation_type is not None:
            rows = [s for s in rows if s["donation_type"] == donation_type]
        if status is not None:
            rows = [s for s in rows if s["status"] == status]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_slot(s) for s in page], limit, offset, total)


@bp.route("/blood-bank/slots/<slot_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "InventoryManager", "Donor")
def get_slot(slot_id):
    with db.lock:
        slot = lookup.slot(slot_id)
        return success(serialize_slot(slot))


@bp.route("/blood-bank/slots/<slot_id>/close", methods=["POST"])
@require_roles("CenterAdmin")
def close_slot(slot_id):
    with db.lock:
        slot = lookup.slot(slot_id)
        slot["status"] = "CLOSED"
        db.touch(slot)
        return success(serialize_slot(slot))
