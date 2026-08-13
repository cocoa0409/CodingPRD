"""Snow event routes: CRUD, event actions, closure actions, dispatch, cost."""

from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_ACTIVE_NOTAMS_REMAIN, ERR_AIRLINE_ACK_REQUIRED,
                    ERR_EQUIPMENT_READINESS_SHORTFALL, ERR_EVENT_NOT_FOUND,
                    ERR_INVALID_EVENT_STATE, ERR_RUNWAYS_NOT_CLOSED,
                    ERR_SURFACE_NOT_CLEARED, validation, not_found)
from middleware import require_roles
from response import success_array_no_pagination, success_list, success_object
from services.core import (get_pagination, is_int, is_number, new_id,
                           now_iso_ms, paginate, to_decimal)
from services.domain import (recompute_event_costs, serialize_event,
                             serialize_surface)

bp = Blueprint("snow_events", __name__)


def _get_event_or_404(event_id: str) -> dict:
    ev = db.snow_events.get(event_id)
    if not ev:
        raise not_found(ERR_EVENT_NOT_FOUND, "SnowEvent not found")
    return ev


@bp.route("/snow-events", methods=["POST"])
def create_event():
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    for f in ("event_code", "season_label", "chemical_limit_lbs", "budget_cents"):
        if f not in body:
            raise validation(f"Missing required field: {f}")
    if not isinstance(body["event_code"], str) or not body["event_code"]:
        raise validation("event_code must be a non-empty string")
    if not isinstance(body["season_label"], str):
        raise validation("season_label must be a string")
    if not is_number(body["chemical_limit_lbs"]):
        raise validation("chemical_limit_lbs must be a number")
    chem_limit = to_decimal(body["chemical_limit_lbs"], "chemical_limit_lbs")
    if chem_limit <= 0:
        raise validation("chemical_limit_lbs must be > 0")
    if not is_int(body["budget_cents"]):
        raise validation("budget_cents must be an integer")
    if body["budget_cents"] < 0:
        raise validation("budget_cents must be >= 0")
    # uniqueness on event_code
    for ev in db.snow_events.values():
        if ev["event_code"] == body["event_code"]:
            raise validation("event_code must be unique")
    now = now_iso_ms()
    ev = {
        "id": new_id(),
        "event_code": body["event_code"],
        "season_label": body["season_label"],
        "chemical_limit_lbs": chem_limit,
        "budget_cents": body["budget_cents"],
        "status": "FORECAST",
        "closure_status": "NONE",
        "airline_acknowledged": False,
        "activated_at": None,
        "estimated_cost_cents": 0,
        "actual_cost_cents": 0,
        "chemical_used_lbs": Decimal(0),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.snow_events[ev["id"]] = ev
    return success_object(serialize_event(ev), 201)


@bp.route("/snow-events", methods=["GET"])
def list_events():
    user_id, role = require_roles("OpsController", "AirlineCoordinator", "SystemAdmin")
    limit, offset = get_pagination(request.args)
    items = list(db.snow_events.values())
    status_q = request.args.get("status")
    season_q = request.args.get("season_label")
    if status_q:
        items = [e for e in items if e["status"] == status_q]
    if season_q:
        items = [e for e in items if e["season_label"] == season_q]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.route("/snow-events/<event_id>", methods=["GET"])
def get_event(event_id):
    user_id, role = require_roles("OpsController", "AirlineCoordinator", "SystemAdmin")
    ev = _get_event_or_404(event_id)
    return success_object(serialize_event(ev))


@bp.route("/snow-events/<event_id>/event-actions", methods=["POST"])
def event_actions(event_id):
    user_id, role = require_roles("OpsController")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    valid_actions = {"ACTIVATE", "ESCALATE", "DE_ESCALATE", "STAND_DOWN", "CLOSE"}
    if action not in valid_actions:
        raise validation("Unknown action")
    ev = _get_event_or_404(event_id)

    # state precondition: check action validity vs current status
    transitions = {
        ("FORECAST", "ACTIVATE"): "ACTIVATED",
        ("ACTIVATED", "ESCALATE"): "ESCALATED",
        ("ESCALATED", "DE_ESCALATE"): "ACTIVATED",
        ("ACTIVATED", "STAND_DOWN"): "STANDING_DOWN",
        ("ESCALATED", "STAND_DOWN"): "STANDING_DOWN",
        ("STANDING_DOWN", "CLOSE"): "CLOSED",
    }
    key = (ev["status"], action)
    if key not in transitions:
        raise ApiError(ERR_INVALID_EVENT_STATE, 409,
                       f"Action {action} not valid from status {ev['status']}")

    # business checks (priority 14, 15, 16)
    if action == "ACTIVATE":
        ready_count = sum(1 for u in db.equipment_units.values()
                          if u["readiness"] == "READY")
        if ready_count < 3:
            raise ApiError(ERR_EQUIPMENT_READINESS_SHORTFALL, 409,
                           "Fewer than 3 READY EquipmentUnits")
    elif action == "STAND_DOWN":
        for s in db.airfield_surfaces.values():
            if s["status"] != "OPEN":
                raise ApiError(ERR_SURFACE_NOT_CLEARED, 409,
                               "Not all surfaces OPEN")
    elif action == "CLOSE":
        for n in db.notams.values():
            if n["event_id"] == event_id and n["status"] == "ISSUED":
                raise ApiError(ERR_ACTIVE_NOTAMS_REMAIN, 409,
                               "Active NOTAMs remain")

    new_status = transitions[key]
    ev["status"] = new_status
    if action == "ACTIVATE":
        # activated_at = current logical clock
        clk = db.logical_clock
        ev["activated_at"] = clk.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{clk.microsecond // 1000:03d}Z"
    if action == "STAND_DOWN":
        if ev["closure_status"] == "RATIFIED":
            ev["closure_status"] = "LIFTED"
        elif ev["closure_status"] == "PROPOSED":
            ev["closure_status"] = "NONE"
            ev["airline_acknowledged"] = False
    if action == "CLOSE":
        # actual frozen as final; estimated recomputed
        recompute_event_costs(ev)
    ev["version"] += 1
    ev["updated_at"] = now_iso_ms()
    return success_object(serialize_event(ev))


@bp.route("/snow-events/<event_id>/closure-actions", methods=["POST"])
def closure_actions(event_id):
    # Auth: must be authenticated first; role validated per action
    user_id, role = require_roles("OpsController", "AirlineCoordinator")
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if not isinstance(action, str) or not action:
        raise validation("action is required")
    if action not in {"PROPOSE", "ACKNOWLEDGE", "RATIFY"}:
        raise validation("Unknown action")
    # Per-action role authorization
    if action == "ACKNOWLEDGE":
        if role != "AirlineCoordinator":
            from errors import unauthorized_role
            raise unauthorized_role()
    else:  # PROPOSE or RATIFY
        if role != "OpsController":
            from errors import unauthorized_role
            raise unauthorized_role()

    ev = _get_event_or_404(event_id)

    if action == "PROPOSE":
        if ev["status"] not in ("ACTIVATED", "ESCALATED"):
            raise ApiError(ERR_INVALID_EVENT_STATE, 409,
                           "PROPOSE requires ACTIVATED/ESCALATED event")
        if ev["closure_status"] != "NONE":
            raise ApiError(ERR_INVALID_EVENT_STATE, 409,
                           "PROPOSE requires closure_status NONE")
        ev["closure_status"] = "PROPOSED"
        ev["airline_acknowledged"] = False
        ev["version"] += 1
        ev["updated_at"] = now_iso_ms()
    elif action == "ACKNOWLEDGE":
        if ev["closure_status"] != "PROPOSED":
            raise ApiError(ERR_INVALID_EVENT_STATE, 409,
                           "ACKNOWLEDGE requires closure_status PROPOSED")
        ev["airline_acknowledged"] = True
        ev["version"] += 1
        ev["updated_at"] = now_iso_ms()
    elif action == "RATIFY":
        if ev["closure_status"] != "PROPOSED":
            raise ApiError(ERR_INVALID_EVENT_STATE, 409,
                           "RATIFY requires closure_status PROPOSED")
        # runways check first
        for s in db.airfield_surfaces.values():
            if s["surface_type"] == "RUNWAY" and s["status"] != "CLOSED":
                raise ApiError(ERR_RUNWAYS_NOT_CLOSED, 409,
                               "Not all RUNWAY surfaces CLOSED")
        if not ev["airline_acknowledged"]:
            raise ApiError(ERR_AIRLINE_ACK_REQUIRED, 409,
                           "Airline acknowledgement required")
        ev["closure_status"] = "RATIFIED"
        ev["version"] += 1
        ev["updated_at"] = now_iso_ms()

    return success_object(serialize_event(ev))


@bp.route("/snow-events/<event_id>/dispatch-order", methods=["GET"])
def dispatch_order(event_id):
    user_id, role = require_roles("OpsController", "MaintenanceLead")
    ev = _get_event_or_404(event_id)
    eligible = [s for s in db.airfield_surfaces.values()
                if s["status"] in ("RESTRICTED", "CLOSED")]
    eligible.sort(key=lambda s: (s["priority_rank"], s["created_at"]))
    return success_array_no_pagination([serialize_surface(s) for s in eligible])


@bp.route("/snow-events/<event_id>/cost-summary", methods=["GET"])
def cost_summary(event_id):
    user_id, role = require_roles("OpsController")
    ev = _get_event_or_404(event_id)
    data = {
        "estimated_cost_cents": ev["estimated_cost_cents"],
        "actual_cost_cents": ev["actual_cost_cents"],
        "chemical_used_lbs": float(ev["chemical_used_lbs"]),
    }
    return success_object(data)
