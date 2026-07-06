"""TimeSlot endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import lookup
from services.common import (
    require_int, require_datetime, touch, base_record, sort_and_paginate,
)
from services.serialize import serialize_time_slot

bp = Blueprint("time_slots", __name__)

READ_ROLES = {"OpsManager", "BoxOffice", "Guest", "Actor"}


@bp.route("/attractions/<attraction_id>/time-slots", methods=["POST"])
def create_time_slot(attraction_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    attraction = lookup.attraction(attraction_id)
    body = get_json_body()
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    capacity = require_int(body, "capacity", minimum=1)

    if window_end <= window_start:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       "window_end must be after window_start.")

    # Overlap check first (validation priority 13): a new slot must not overlap an
    # existing SCHEDULED slot on the same attraction. Half-open [start, end)
    # intersection; touching windows (existing.window_end == new.window_start) are
    # allowed with zero buffer (PRD §3.2).
    for existing in db.time_slots.values():
        if existing["attraction_id"] != attraction_id:
            continue
        if existing["status"] != "SCHEDULED":
            continue
        e_start = db.parse_iso(existing["window_start"])
        e_end = db.parse_iso(existing["window_end"])
        if window_start < e_end and e_start < window_end:
            raise ApiError(errors.ERR_SLOT_OVERLAP, 409,
                           "New time slot overlaps an existing SCHEDULED slot.")

    # Capacity must not exceed parent attraction's throughput (priority 14).
    if capacity > attraction["throughput_per_slot"]:
        raise ApiError(errors.ERR_CAPACITY_OVER_THROUGHPUT, 422,
                       "TimeSlot.capacity exceeds attraction.throughput_per_slot.")

    slot = base_record()
    slot.update({
        "attraction_id": attraction["id"],
        "window_start": db.iso(window_start),
        "window_end": db.iso(window_end),
        "capacity": capacity,
        "reserved_count": 0,
        "admitted_count": 0,
        "status": "SCHEDULED",
    })
    db.time_slots[slot["id"]] = slot
    return response.success(serialize_time_slot(slot), 201)


@bp.route("/time-slots/<time_slot_id>", methods=["GET"])
def get_time_slot(time_slot_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    slot = lookup.time_slot(time_slot_id)
    return response.success(serialize_time_slot(slot), 200)


@bp.route("/time-slots", methods=["GET"])
def list_time_slots():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    attraction_id = request.args.get("attraction_id")
    records = list(db.time_slots.values())
    if attraction_id is not None:
        records = [s for s in records if s["attraction_id"] == attraction_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_time_slot(s) for s in page], limit, offset, total, 200
    )
