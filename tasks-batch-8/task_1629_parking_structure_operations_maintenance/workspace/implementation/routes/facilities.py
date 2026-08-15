"""Facility endpoints: onboarding, posture, dashboard, close-of-business (PRD 3.1)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_posture_blocked, err_posture_blocks,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascade import (
    check_release_guards, check_decommission_guards, close_of_business,
)
from services.common import (
    body, require_string, require_int, require_enum, optional_number,
    parse_pagination, paginate, get_facility_path, facility_view,
)

bp = Blueprint("facilities", __name__)

POSTURES = {"NORMAL", "EVENT_SURGE", "RESTRICTED", "CLOSED_TEMPORARY", "DECOMMISSIONED"}

# Manual transition edges: {from_state: {allowed manual targets}}
_MANUAL_EDGES = {
    "NORMAL": {"RESTRICTED", "CLOSED_TEMPORARY", "DECOMMISSIONED"},
    "RESTRICTED": {"CLOSED_TEMPORARY", "NORMAL", "DECOMMISSIONED"},
    "CLOSED_TEMPORARY": {"NORMAL", "DECOMMISSIONED"},
    "EVENT_SURGE": set(),
    "DECOMMISSIONED": set(),
}


@bp.post("/ops/facilities")
def create_facility():
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    payload = body()
    name = require_string(payload, "name")
    total_spaces = require_int(payload, "total_spaces", minimum=0, exclusive_min=True)
    monthly_capacity = require_int(payload, "monthly_capacity", minimum=0)
    event_pool_spaces = require_int(payload, "event_pool_spaces", minimum=0)
    levy_pct = optional_number(payload, "levy_pct", default=0.1, minimum=0, maximum=1)
    ent = {
        "id": db.new_id(),
        "name": name,
        "total_spaces": total_spaces,
        "monthly_capacity": monthly_capacity,
        "event_pool_spaces": event_pool_spaces,
        "levy_pct": levy_pct,
        "posture": "NORMAL",
        "closed_spaces": 0,
        "capital_reserve_cents": 0,
        "deposit_liability_cents": 0,
        "cumulative_collected_cents": 0,
        "last_close_date": None,
    }
    db.stamp_new(ent)
    db.facilities[ent["id"]] = ent
    return success_object(facility_view(ent), status=201)


@bp.get("/ops/facilities/<facility_id>")
def get_facility_route(facility_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    f = get_facility_path(facility_id)
    return success_object(facility_view(f))


@bp.get("/ops/facilities")
def list_facilities():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.facilities.values())
    posture = request.args.get("posture")
    if posture is not None:
        items = [f for f in items if f["posture"] == posture]
    page, total = paginate(items, limit, offset)
    return success_list([facility_view(f) for f in page], limit, offset, total)


@bp.post("/ops/facilities/<facility_id>/transition-posture")
def transition_posture(facility_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    f = get_facility_path(facility_id)
    payload = body()
    target = require_enum(payload, "target_posture", POSTURES)
    # terminal lockdown first (state legality)
    if f["posture"] == "DECOMMISSIONED":
        raise err_invalid_state("facility is DECOMMISSIONED (terminal)")
    # EVENT_SURGE is never a manual target
    if target == "EVENT_SURGE":
        raise err_posture_blocked("EVENT_SURGE is never a manual posture target")
    if target not in _MANUAL_EDGES.get(f["posture"], set()):
        raise err_invalid_state(
            f"manual posture transition {f['posture']} -> {target} not permitted")
    if target == "NORMAL":
        check_release_guards(f)
    elif target == "DECOMMISSIONED":
        check_decommission_guards(f)
    f["posture"] = target
    db.touch(f)  # every manual posture transition advances version by one
    return success_object(facility_view(f))


@bp.post("/ops/facilities/<facility_id>/close-of-business")
def close_of_business_route(facility_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    f = get_facility_path(facility_id)
    if f["posture"] == "DECOMMISSIONED":
        raise err_invalid_state("facility is DECOMMISSIONED")
    now = db.now_dt()
    business_date = now.date().isoformat()
    if f["last_close_date"] is not None and business_date <= f["last_close_date"]:
        raise err_invalid_state("business date must be strictly after last_close_date")
    summary = close_of_business(f, now)
    return success_object(summary)


@bp.get("/ops/facilities/<facility_id>/dashboard")
def dashboard(facility_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    f = get_facility_path(facility_id)
    view = facility_view(f)
    return success_object({
        "posture": f["posture"],
        "occupied_spaces": view["occupied_spaces"],
        "closed_spaces": f["closed_spaces"],
        "available_transient_spaces": f["total_spaces"] - f["closed_spaces"] - view["occupied_spaces"],
        "monthly_allocated": view["monthly_allocated"],
        "monthly_capacity": f["monthly_capacity"],
        "capital_reserve_cents": f["capital_reserve_cents"],
        "deposit_liability_cents": f["deposit_liability_cents"],
        "cumulative_collected_cents": f["cumulative_collected_cents"],
    })
