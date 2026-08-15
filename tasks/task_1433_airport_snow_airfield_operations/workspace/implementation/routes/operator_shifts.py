"""Operator shift routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_EQUIPMENT_NOT_FOUND, ERR_EQUIPMENT_NOT_READY,
                    ERR_EVENT_NOT_ACTIVE, ERR_EVENT_NOT_FOUND,
                    ERR_INVALID_SHIFT_STATE, ERR_SHIFT_NOT_FOUND,
                    ERR_SHIFT_OVERLAP, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, parse_iso, round_cents,
                           to_decimal)
from services.domain import (compute_shift_line_cost_cents,
                             recompute_event_costs, serialize_operator_shift)

bp = Blueprint("operator_shifts", __name__)


def _get_shift_or_404(shift_id: str) -> dict:
    s = db.operator_shifts.get(shift_id)
    if not s:
        raise not_found(ERR_SHIFT_NOT_FOUND, "OperatorShift not found")
    return s


def _check_overlap(operator_code: str, start_dt, end_dt, exclude_id=None) -> bool:
    """Half-open [start, end) overlap with another non-CANCELLED shift of same
    operator. Touching endpoints (end == start) are allowed."""
    for s in db.operator_shifts.values():
        if s["operator_code"] != operator_code:
            continue
        if s["status"] == "CANCELLED":
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        other_start = s["_start_dt"]
        other_end = s["_end_dt"]
        # overlap if start < other_end AND other_start < end
        if start_dt < other_end and other_start < end_dt:
            return True
    return False


@bp.route("/operator-shifts", methods=["POST"])
def create_shift():
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    for f in ("operator_code", "event_id", "base_rate_cents_per_hour",
              "start_utc", "end_utc"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not isinstance(body["operator_code"], str) or not body["operator_code"]:
        raise validation("operator_code must be a non-empty string")
    if not is_int(body["base_rate_cents_per_hour"]):
        raise validation("base_rate_cents_per_hour must be an integer")
    if body["base_rate_cents_per_hour"] < 0:
        raise validation("base_rate_cents_per_hour must be >= 0")
    start_dt = parse_iso(body["start_utc"], "start_utc")
    end_dt = parse_iso(body["end_utc"], "end_utc")
    if start_dt >= end_dt:
        raise validation("start_utc must be < end_utc")

    ev = db.snow_events.get(body["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")

    equipment_unit_id = body.get("equipment_unit_id")
    unit = None
    if equipment_unit_id is not None:
        unit = db.equipment_units.get(equipment_unit_id)
        if not unit:
            raise not_found(ERR_EQUIPMENT_NOT_FOUND, "EquipmentUnit not found")

    # event state gate
    if ev["status"] not in ("ACTIVATED", "ESCALATED"):
        raise ApiError(ERR_EVENT_NOT_ACTIVE, 409,
                       "Referenced SnowEvent not ACTIVATED/ESCALATED")

    # overlap check
    if _check_overlap(body["operator_code"], start_dt, end_dt):
        raise ApiError(ERR_SHIFT_OVERLAP, 409, "Shift window overlaps")

    # equipment readiness
    if unit and unit["readiness"] != "READY":
        raise ApiError(ERR_EQUIPMENT_NOT_READY, 409,
                       "Equipment unit is not READY")

    now = now_iso_ms()
    s = {
        "id": new_id(),
        "operator_code": body["operator_code"],
        "event_id": body["event_id"],
        "equipment_unit_id": equipment_unit_id,
        "base_rate_cents_per_hour": body["base_rate_cents_per_hour"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "worked_hours": None,
        "line_cost_cents": 0,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.operator_shifts[s["id"]] = s
    recompute_event_costs(ev)
    ev["updated_at"] = now_iso_ms()
    return success_object(serialize_operator_shift(s), 201)


@bp.route("/operator-shifts/<shift_id>/shift-actions", methods=["POST"])
def shift_actions(shift_id):
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in ("COMPLETE", "CANCEL"):
        raise validation("Unknown action")

    s = _get_shift_or_404(shift_id)
    ev = db.snow_events.get(s["event_id"])
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")

    if action == "COMPLETE":
        if s["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_SHIFT_STATE, 409,
                           "COMPLETE requires SCHEDULED")
        if "worked_hours" not in body:
            raise validation("worked_hours is required for COMPLETE")
        if not is_number(body["worked_hours"]):
            raise validation("worked_hours must be a number")
        worked = to_decimal(body["worked_hours"], "worked_hours")
        if worked <= 0:
            raise validation("worked_hours must be > 0")
        s["worked_hours"] = worked
        s["status"] = "COMPLETED"
        s["line_cost_cents"] = compute_shift_line_cost_cents(s, worked)
        s["version"] += 1
        s["updated_at"] = now_iso_ms()
        recompute_event_costs(ev)
        ev["updated_at"] = now_iso_ms()
    else:  # CANCEL
        if s["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_SHIFT_STATE, 409,
                           "CANCEL requires SCHEDULED")
        s["status"] = "CANCELLED"
        s["version"] += 1
        s["updated_at"] = now_iso_ms()
        recompute_event_costs(ev)
        ev["updated_at"] = now_iso_ms()

    return success_object(serialize_operator_shift(s))


@bp.route("/operator-shifts", methods=["GET"])
def list_shifts():
    user_id, role = require_roles("OpsController")
    limit, offset = get_pagination(request.args)
    items = list(db.operator_shifts.values())
    for f in ("operator_code", "event_id", "equipment_unit_id", "status"):
        q = request.args.get(f)
        if q:
            items = [s for s in items if s[f] == q]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_operator_shift(s) for s in page],
                        limit, offset, total)


@bp.route("/operator-shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    user_id, role = require_roles("OpsController")
    s = _get_shift_or_404(shift_id)
    return success_object(serialize_operator_shift(s))
