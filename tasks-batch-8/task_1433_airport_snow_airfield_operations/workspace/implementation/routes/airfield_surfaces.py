"""Airfield surface routes."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_EVENT_NOT_ACTIVE, ERR_EVENT_NOT_FOUND,
                    ERR_INVALID_SURFACE_STATE, ERR_REOPEN_FRICTION_TOO_LOW,
                    ERR_SURFACE_NOT_FOUND, not_found, validation)
from middleware import require_roles
from response import success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, to_decimal)
from services.domain import (recompute_active_notam_count, serialize_surface,
                             supersede_notams_for_report)

bp = Blueprint("airfield_surfaces", __name__)


def _get_surface_or_404(surface_id: str) -> dict:
    s = db.airfield_surfaces.get(surface_id)
    if not s:
        raise not_found(ERR_SURFACE_NOT_FOUND, "AirfieldSurface not found")
    return s


@bp.route("/airfield-surfaces", methods=["POST"])
def create_surface():
    user_id, role = require_roles("SystemAdmin")
    body = request.get_json(silent=True) or {}
    for f in ("surface_code", "surface_type", "length_ft", "width_ft",
              "priority_rank"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not isinstance(body["surface_code"], str) or not body["surface_code"]:
        raise validation("surface_code must be a non-empty string")
    if body["surface_type"] not in ("RUNWAY", "TAXIWAY", "APRON"):
        raise validation("invalid surface_type")
    if not is_number(body["length_ft"]) or not is_number(body["width_ft"]):
        raise validation("length_ft / width_ft must be numbers")
    length = to_decimal(body["length_ft"], "length_ft")
    width = to_decimal(body["width_ft"], "width_ft")
    if length <= 0 or width <= 0:
        raise validation("length_ft and width_ft must be > 0")
    if not is_int(body["priority_rank"]):
        raise validation("priority_rank must be an integer")
    for s in db.airfield_surfaces.values():
        if s["surface_code"] == body["surface_code"]:
            raise validation("surface_code must be unique")
    now = now_iso_ms()
    s = {
        "id": new_id(),
        "surface_code": body["surface_code"],
        "surface_type": body["surface_type"],
        "length_ft": length,
        "width_ft": width,
        "area_sqft": length * width,
        "priority_rank": body["priority_rank"],
        "status": "OPEN",
        "current_condition_code": None,
        "active_notam_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.airfield_surfaces[s["id"]] = s
    return success_object(serialize_surface(s), 201)


@bp.route("/airfield-surfaces", methods=["GET"])
def list_surfaces():
    user_id, role = require_roles("OpsController", "AirfieldInspector",
                                  "MaintenanceLead", "SystemAdmin")
    limit, offset = get_pagination(request.args)
    items = list(db.airfield_surfaces.values())
    status_q = request.args.get("status")
    type_q = request.args.get("surface_type")
    if status_q:
        items = [s for s in items if s["status"] == status_q]
    if type_q:
        items = [s for s in items if s["surface_type"] == type_q]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_surface(s) for s in page], limit, offset, total)


@bp.route("/airfield-surfaces/<surface_id>", methods=["GET"])
def get_surface(surface_id):
    user_id, role = require_roles("OpsController", "AirfieldInspector",
                                  "MaintenanceLead", "SystemAdmin")
    s = _get_surface_or_404(surface_id)
    return success_object(serialize_surface(s))


@bp.route("/airfield-surfaces/<surface_id>/surface-actions", methods=["POST"])
def surface_actions(surface_id):
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in ("RESTRICT", "CLOSE", "REOPEN", "CLEAR"):
        raise validation("Unknown action")
    if "event_id" not in body:
        raise validation("event_id is required")
    event_id = body["event_id"]

    s = _get_surface_or_404(surface_id)
    ev = db.snow_events.get(event_id)
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")

    # state preconditions: valid transition
    transitions = {
        ("OPEN", "RESTRICT"): "RESTRICTED",
        ("OPEN", "CLOSE"): "CLOSED",
        ("RESTRICTED", "CLOSE"): "CLOSED",
        ("CLOSED", "REOPEN"): "RESTRICTED",
        ("RESTRICTED", "CLEAR"): "OPEN",
    }
    key = (s["status"], action)
    if key not in transitions:
        raise ApiError(ERR_INVALID_SURFACE_STATE, 409,
                       f"Action {action} not valid from status {s['status']}")

    # cross-entity event state gate
    if ev["status"] not in ("ACTIVATED", "ESCALATED"):
        raise ApiError(ERR_EVENT_NOT_ACTIVE, 409,
                       "Referenced SnowEvent not ACTIVATED/ESCALATED")

    # REOPEN friction floor
    if action == "REOPEN":
        latest = _latest_reported_assessment(surface_id)
        if not latest or latest["braking_action"] not in ("GOOD", "MEDIUM"):
            raise ApiError(ERR_REOPEN_FRICTION_TOO_LOW, 409,
                           "Latest REPORTED friction not GOOD/MEDIUM")

    # apply transition
    s["status"] = transitions[key]
    if action == "CLOSE":
        # cascade link 1: supersede FILED reports on this surface
        superseded_ids = []
        for r in db.condition_reports.values():
            if r["surface_id"] == surface_id and r["status"] == "FILED":
                r["status"] = "SUPERSEDED"
                r["version"] += 1
                r["updated_at"] = now_iso_ms()
                superseded_ids.append(r["id"])
        # cascade link 2 & 3: flip ISSUED notams sourced from those reports,
        # recompute active_notam_count
        for rid in superseded_ids:
            supersede_notams_for_report(rid)
        recompute_active_notam_count(surface_id)

    s["version"] += 1
    s["updated_at"] = now_iso_ms()
    return success_object(serialize_surface(s))


def _latest_reported_assessment(surface_id: str):
    cands = [a for a in db.friction_assessments.values()
             if a["surface_id"] == surface_id and a["status"] == "REPORTED"]
    if not cands:
        return None
    cands.sort(key=lambda a: a["created_at"])
    return cands[-1]
