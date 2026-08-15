"""CraneSlot endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("crane_slots", __name__)

VALID_SLOT_STATUSES = {"OPEN", "CLOSED"}


@bp.route("/genset-packaging/crane-slots", methods=["POST"])
def create_crane_slot():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    service_date = mw.require_string(body, "service_date")
    window_start_hour = mw.require_int(body, "window_start_hour", minimum=0)
    window_end_hour = mw.require_int(body, "window_end_hour", maximum=24)
    buffer_hours = mw.optional_number(body, "buffer_hours", 0.5, minimum=0)
    status = mw.optional_enum(body, "status", VALID_SLOT_STATUSES, "OPEN")

    if window_start_hour >= window_end_hour:
        raise errors.invalid_request("window_start_hour must be strictly before window_end_hour")

    window_length = window_end_hour - window_start_hour
    record = {
        "service_date": service_date,
        "window_start_hour": window_start_hour,
        "window_end_hour": window_end_hour,
        "buffer_hours": buffer_hours,
        "reserved_hours": 0,
        "free_hours": window_length,
        "status": status,
    }
    db.stamp_new(record)
    db.crane_slots[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/crane-slots/<craneSlotId>", methods=["GET"])
def get_crane_slot(craneSlotId):
    mw.authenticate()
    record = db.crane_slots.get(craneSlotId)
    if record is None:
        raise errors.not_found("Crane slot not found")
    return resp.success_object(record)
