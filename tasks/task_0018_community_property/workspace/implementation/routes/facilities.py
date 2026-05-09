"""POST /facilities — create a Facility."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_VALIDATION
from middleware import require_roles
from response import success
from services.common import stamp_create
from utils import get_body, require_field, to_decimal

bp = Blueprint("facilities", __name__)

VALID_FACILITY_TYPES = {"CLUBHOUSE", "GYM", "MEETING_ROOM"}
VALID_SLOT_MINUTES = {30, 60, 120, 180, 240}


@bp.post("/facilities")
@require_roles("PropertyManager")
def create_facility():
    body = get_body()
    facility_type = require_field(body, "facility_type")
    name = require_field(body, "name")
    slot_minutes = require_field(body, "slot_minutes")
    capacity_per_slot = body.get("capacity_per_slot", 1)
    cancellation_window_hours = body.get("cancellation_window_hours", 24)
    damage_deposit = body.get("damage_deposit", 0)

    if facility_type not in VALID_FACILITY_TYPES:
        raise APIError(ERR_VALIDATION, "Invalid facility_type.", 422)
    if slot_minutes not in VALID_SLOT_MINUTES:
        raise APIError(ERR_VALIDATION, "Invalid slot_minutes.", 422)
    if not isinstance(capacity_per_slot, int) or capacity_per_slot < 1:
        raise APIError(ERR_VALIDATION, "capacity_per_slot must be >= 1.", 422)
    if not isinstance(cancellation_window_hours, int) or cancellation_window_hours < 0:
        raise APIError(ERR_VALIDATION, "cancellation_window_hours must be a non-negative integer.", 422)

    deposit_d = to_decimal(damage_deposit)
    if deposit_d < 0:
        raise APIError(ERR_VALIDATION, "damage_deposit must be >= 0.", 422)

    # Uniqueness on name
    for f in db.facilities.values():
        if f.get("name") == name:
            raise APIError(ERR_VALIDATION, "Facility name already exists.", 422)

    facility = {
        "facility_type": facility_type,
        "name": name,
        "slot_minutes": slot_minutes,
        "capacity_per_slot": capacity_per_slot,
        "cancellation_window_hours": cancellation_window_hours,
        "damage_deposit": float(deposit_d),
    }
    stamp_create(facility)
    db.facilities[facility["id"]] = facility
    return success(facility, status=201)
