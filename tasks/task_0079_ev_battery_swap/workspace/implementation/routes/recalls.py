"""Manufacturer recall endpoint."""

from flask import Blueprint

from db import DB
from errors import ERR_BATTERY_RECALLED, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.common import bump_version, get_body, require_string
from services.lookups import charging_slot_for_battery


bp = Blueprint("recalls", __name__, url_prefix="/swap-stations")


@bp.route("/recalls", methods=["POST"])
@auth_required(["PlatformAdmin"])
def apply_recall():
    body = get_body()
    battery_model_code = require_string(body, "battery_model_code")
    serial_numbers = body.get("serial_numbers")
    if not isinstance(serial_numbers, list) or not serial_numbers:
        raise_error(ERR_INVALID_INPUT, "serial_numbers must be a non-empty list")
    for s in serial_numbers:
        if not isinstance(s, str) or not s:
            raise_error(ERR_INVALID_INPUT, "serial_numbers entries must be non-empty strings")

    # Find candidate batteries first; reject if any is already IN_USE.
    candidates = []
    for b in DB["batteries"].values():
        if (b.get("battery_model_code") == battery_model_code
                and b.get("serial_number") in serial_numbers):
            candidates.append(b)

    # Per PRD §2.9: applying a recall to a battery in IN_USE is rejected.
    for b in candidates:
        if b.get("status") == "IN_USE":
            raise_error(ERR_BATTERY_RECALLED,
                        "Cannot apply recall to a battery currently IN_USE")

    affected = []
    for b in candidates:
        prev_status = b.get("status")
        if prev_status not in {"IDLE", "CHARGING"}:
            continue
        station = DB["stations"].get(b.get("station_id"))
        if prev_status == "IDLE" and station is not None:
            station["idle_battery_count"] = max(
                0, int(station.get("idle_battery_count", 0)) - 1
            )
            bump_version(station)
        elif prev_status == "CHARGING":
            if station is not None:
                station["charging_battery_count"] = max(
                    0, int(station.get("charging_battery_count", 0)) - 1
                )
                bump_version(station)
            slot = charging_slot_for_battery(b["id"])
            if slot is not None:
                slot["status"] = "EMPTY"
                slot["battery_id"] = None
                bump_version(slot)
        b["recall_flag"] = True
        b["status"] = "RETIRED"
        b["cascade_stage"] = "END_OF_LIFE"
        bump_version(b)
        append_audit("RECALL_APPLIED", "Battery", b["id"], prev_status, "RETIRED")
        affected.append(b["id"])

    return success_response(
        {
            "battery_model_code": battery_model_code,
            "serial_numbers": list(serial_numbers),
            "affected_battery_ids": affected,
            "affected_count": len(affected),
        },
        http_status=201,
    )
