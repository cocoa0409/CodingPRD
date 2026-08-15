"""Utility meter readings (append-only events with auto-suspend cascade)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_number,
    check_string,
)
from response import success_object
from services.core import new_event, _touch, recompute_shift_aggregates
from services.serializers import serialize_utility_reading

bp = Blueprint("utility", __name__)

METER_TYPES = ("PROCESS_WATER", "CHILLER_WATER")


@bp.route("/poultry/utility-readings", methods=["POST"])
def create_reading():
    require_roles("QATechnician")
    body = get_json_body()
    check_no_unknown(body, {"shift_id", "meter_type", "gallons"})
    check_required(body, ["shift_id", "meter_type", "gallons"])
    check_string(body["shift_id"], "shift_id")
    check_enum(body["meter_type"], METER_TYPES, "meter_type")
    check_number(body["gallons"], "gallons", min_value=0, exclusive_min=True)

    shift = db.shifts.get(body["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)

    reading = new_event()
    reading.update({
        "shift_id": shift["id"],
        "meter_type": body["meter_type"],
        "gallons": body["gallons"],
        "recorded_at": db.clock_now(),
    })
    db.utility_readings[reading["id"]] = reading

    # Recompute aggregates and breach flags
    was_breach = bool(shift.get("water_breach_active"))
    recompute_shift_aggregates(shift)
    _touch(shift)
    now_breach = bool(shift.get("water_breach_active"))

    # Auto-suspend: PROCESS_WATER reading that flips breach false->true while RUNNING
    if (
        body["meter_type"] == "PROCESS_WATER"
        and not was_breach
        and now_breach
        and shift["status"] == "RUNNING"
    ):
        shift["status"] = "SUSPENDED"
        shift["suspend_reason"] = "WATER_LIMIT_BREACH"
        _touch(shift)
        for run in db.line_runs.values():
            if run["shift_id"] == shift["id"] and run["status"] == "RUNNING":
                run["status"] = "PAUSED"
                run["auto_paused"] = True
                _touch(run)
        for b in db.deboning_batches.values():
            if b["shift_id"] == shift["id"] and b["status"] == "IN_PROGRESS":
                b["status"] = "ON_HOLD"
                _touch(b)

    return success_object(serialize_utility_reading(reading), 201)
