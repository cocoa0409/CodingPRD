"""Equipment unit routes."""

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_EQUIPMENT_NOT_FOUND, ERR_VALIDATION,
                    not_found, validation)
from middleware import require_roles
from response import success_object
from services.core import is_int, new_id, now_iso_ms
from services.domain import serialize_equipment_unit

bp = Blueprint("equipment_units", __name__)

UNIT_TYPES = {"PLOW", "BROOM", "DEICER", "BLOWER"}


@bp.route("/equipment-units", methods=["POST"])
def create_unit():
    user_id, role = require_roles("SystemAdmin")
    body = request.get_json(silent=True) or {}
    for f in ("unit_code", "unit_type", "hourly_rate_cents"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not isinstance(body["unit_code"], str) or not body["unit_code"]:
        raise validation("unit_code must be a non-empty string")
    if body["unit_type"] not in UNIT_TYPES:
        raise validation("invalid unit_type")
    if not is_int(body["hourly_rate_cents"]):
        raise validation("hourly_rate_cents must be an integer")
    if body["hourly_rate_cents"] < 0:
        raise validation("hourly_rate_cents must be >= 0")
    for u in db.equipment_units.values():
        if u["unit_code"] == body["unit_code"]:
            raise validation("unit_code must be unique")
    now = now_iso_ms()
    u = {
        "id": new_id(),
        "unit_code": body["unit_code"],
        "unit_type": body["unit_type"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "readiness": "READY",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.equipment_units[u["id"]] = u
    return success_object(serialize_equipment_unit(u), 201)


@bp.route("/equipment-units/<unit_id>/readiness-actions", methods=["POST"])
def readiness_actions(unit_id):
    user_id, role = require_roles("MaintenanceLead")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in ("TAKE_OUT_OF_SERVICE", "RETURN_TO_SERVICE"):
        raise validation("Unknown action")
    u = db.equipment_units.get(unit_id)
    if not u:
        raise not_found(ERR_EQUIPMENT_NOT_FOUND, "EquipmentUnit not found")

    transitions = {
        ("READY", "TAKE_OUT_OF_SERVICE"): "OUT_OF_SERVICE",
        ("OUT_OF_SERVICE", "RETURN_TO_SERVICE"): "READY",
    }
    key = (u["readiness"], action)
    if key not in transitions:
        # Use ERR_VALIDATION? Spec doesn't define specific code — use 409 with validation
        # Realistically this shouldn't happen; we return a generic state error.
        raise ApiError("ERR_INVALID_EQUIPMENT_STATE", 409,
                       f"Action {action} not valid from readiness {u['readiness']}")
    u["readiness"] = transitions[key]
    u["version"] += 1
    u["updated_at"] = now_iso_ms()
    return success_object(serialize_equipment_unit(u))
