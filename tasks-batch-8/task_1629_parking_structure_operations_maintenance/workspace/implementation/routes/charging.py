"""Charging session endpoints (PRD 3.8)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_charger_unavailable,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_number, optional_int,
    parse_pagination, paginate, require_ref, optional_ref, get_charging_session, public_view,
)

bp = Blueprint("charging", __name__)

START_ROLES = ["MonthlyParker", "ParkingAttendant", "MaintenanceSupervisor"]


@bp.post("/ops/charging-sessions")
def create_charging_session():
    actor = get_actor()
    require_roles(actor, START_ROLES)
    payload = body()
    charger = require_ref(payload, db.ev_chargers, "charger_id")
    agreement = optional_ref(payload, db.monthly_agreements, "agreement_id")
    agreement_id = agreement["id"] if agreement else None
    # three start conditions, all ERR_CHARGER_UNAVAILABLE
    if charger["charger_status"] != "COMMISSIONED":
        raise err_charger_unavailable("charger is not COMMISSIONED")
    if any(s["charger_id"] == charger["id"] and s["session_status"] == "CHARGING"
           for s in db.charging_sessions.values()):
        raise err_charger_unavailable("charger already has a CHARGING session")
    if agreement is not None and agreement["agreement_status"] != "ACTIVE":
        raise err_charger_unavailable("supplied agreement is not ACTIVE")
    ent = {
        "id": db.new_id(),
        "charger_id": charger["id"],
        "agreement_id": agreement_id,
        "session_status": "CHARGING",
        "started_at": db.now_iso(),
        "ended_at": None,
        "kwh_delivered": None,
        "idle_minutes": 0,
    }
    db.stamp_new(ent)
    db.charging_sessions[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/charging-sessions/<charging_session_id>")
def get_charging_session_route(charging_session_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_charging_session(charging_session_id)))


@bp.get("/ops/charging-sessions")
def list_charging_sessions():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.charging_sessions.values())
    for key in ("charger_id", "agreement_id", "session_status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(s) for s in page], limit, offset, total)


@bp.post("/ops/charging-sessions/<charging_session_id>/complete")
def complete_charging_session(charging_session_id):
    actor = get_actor()
    require_roles(actor, START_ROLES)
    s = get_charging_session(charging_session_id)
    payload = body()
    kwh = require_number(payload, "kwh_delivered", minimum=0, exclusive_min=True)
    idle = optional_int(payload, "idle_minutes", default=0, minimum=0)
    if s["session_status"] != "CHARGING":
        raise err_invalid_state("only a CHARGING session may complete")
    s["session_status"] = "COMPLETED"
    s["kwh_delivered"] = kwh
    s["idle_minutes"] = idle
    s["ended_at"] = db.now_iso()
    db.touch(s)
    return success_object(public_view(s))


@bp.post("/ops/charging-sessions/<charging_session_id>/fault")
def fault_charging_session(charging_session_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant", "MaintenanceSupervisor"])
    s = get_charging_session(charging_session_id)
    payload = body()
    require_string(payload, "fault_description")
    if s["session_status"] != "CHARGING":
        raise err_invalid_state("only a CHARGING session may fault")
    s["session_status"] = "FAULTED"
    s["ended_at"] = db.now_iso()
    db.touch(s)
    charger = db.ev_chargers.get(s["charger_id"])
    if charger is not None and charger["charger_status"] == "COMMISSIONED":
        charger["charger_status"] = "OUT_OF_SERVICE"
        db.touch(charger)
    return success_object(public_view(s))
