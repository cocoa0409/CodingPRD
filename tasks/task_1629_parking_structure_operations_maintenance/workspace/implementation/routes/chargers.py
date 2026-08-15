"""EV charger endpoints (PRD 3.8)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_int, parse_pagination, paginate,
    require_ref, get_charger, public_view,
)

bp = Blueprint("chargers", __name__)

MS = ["MaintenanceSupervisor"]


@bp.post("/ops/ev-chargers")
def create_charger():
    actor = get_actor()
    require_roles(actor, MS)
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    label = require_string(payload, "charger_label")
    max_kw = require_int(payload, "max_kw", minimum=0, exclusive_min=True)
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "charger_label": label,
        "max_kw": max_kw,
        "charger_status": "PROPOSED",
        "commissioned_at": None,
        "utilization_session_pct": None,
        "utilization_energy_pct": None,
        "low_util_run_count": 0,
        "utilization_review_flag": False,
    }
    db.stamp_new(ent)
    db.ev_chargers[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/ev-chargers/<ev_charger_id>")
def get_charger_route(ev_charger_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_charger(ev_charger_id)))


@bp.get("/ops/ev-chargers")
def list_chargers():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.ev_chargers.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("charger_status")
    if facility_id is not None:
        items = [c for c in items if c["facility_id"] == facility_id]
    if status is not None:
        items = [c for c in items if c["charger_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(c) for c in page], limit, offset, total)


def _transition(charger_id, from_states, to_state, set_commissioned=False):
    ch = get_charger(charger_id)
    if ch["charger_status"] not in from_states:
        raise err_invalid_state(
            f"charger must be in {sorted(from_states)} for this transition")
    ch["charger_status"] = to_state
    if set_commissioned and ch.get("commissioned_at") is None:
        ch["commissioned_at"] = db.now_iso()
    db.touch(ch)
    return ch


@bp.post("/ops/ev-chargers/<ev_charger_id>/permit")
def permit_charger(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(_transition(ev_charger_id, ["PROPOSED"], "PERMITTED")))


@bp.post("/ops/ev-chargers/<ev_charger_id>/install")
def install_charger(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(_transition(ev_charger_id, ["PERMITTED"], "INSTALLED")))


@bp.post("/ops/ev-chargers/<ev_charger_id>/commission")
def commission_charger(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(
        _transition(ev_charger_id, ["INSTALLED"], "COMMISSIONED", set_commissioned=True)))


@bp.post("/ops/ev-chargers/<ev_charger_id>/take-out-of-service")
def take_out_of_service(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(_transition(ev_charger_id, ["COMMISSIONED"], "OUT_OF_SERVICE")))


@bp.post("/ops/ev-chargers/<ev_charger_id>/return-to-service")
def return_to_service(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(_transition(ev_charger_id, ["OUT_OF_SERVICE"], "COMMISSIONED")))


@bp.post("/ops/ev-chargers/<ev_charger_id>/decommission")
def decommission_charger(ev_charger_id):
    actor = get_actor()
    require_roles(actor, MS)
    return success_object(public_view(_transition(
        ev_charger_id, ["PROPOSED", "PERMITTED", "INSTALLED", "OUT_OF_SERVICE"], "DECOMMISSIONED")))
