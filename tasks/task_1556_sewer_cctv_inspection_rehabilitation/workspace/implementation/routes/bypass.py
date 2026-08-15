"""BypassPlan endpoints."""
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles, technician_capability_check
from response import success_object, success_list
from errors import (
    err_invalid_request, err_invalid_state, err_not_found, err_conflict,
)
from services.common import (
    body, require_int, parse_datetime_field, parse_pagination, paginate,
    get_work_order, get_bypass, sweep_notice_expiry,
    required_pump_gpm, buffered_window_overlap,
)

bp = Blueprint("bypass", __name__)

READ_ROLES = ["DistrictEngineer", "CrewLead"]


def bp_view(b):
    return {
        "id": b["id"],
        "work_order_id": b["work_order_id"],
        "window_start": b["window_start"],
        "window_end": b["window_end"],
        "pump_capacity_gpm": b["pump_capacity_gpm"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/sewer/work-orders/<id>/bypass-plans")
def create_bypass(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    tech = technician_capability_check(actor, "CREW_LEAD")
    if tech["id"] != wo["crew_lead_id"]:
        raise err_conflict("ERR_NOT_ASSIGNED_CREW", "only the assigned crew lead proposes a bypass")
    payload = body()
    ws = parse_datetime_field(payload, "window_start", required=True)
    we = parse_datetime_field(payload, "window_end", required=True)
    if not (we > ws):
        raise err_invalid_request("window_end must be after window_start")
    cap = require_int(payload, "pump_capacity_gpm")
    if cap <= 0:
        raise err_invalid_request("pump_capacity_gpm must be > 0")
    ent = {
        "id": db.new_id(),
        "work_order_id": wo["id"],
        "window_start": _format_iso(ws),
        "window_end": _format_iso(we),
        "pump_capacity_gpm": cap,
        "status": "PROPOSED",
    }
    db.stamp_new(ent)
    db.bypass_plans[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(bp_view(ent), status=201)


@bp.get("/sewer/bypass-plans/<id>")
def get_bypass_route(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    b = get_bypass(id)
    return success_object(bp_view(b))


@bp.get("/sewer/work-orders/<id>/bypass-plans")
def list_bypass_for_wo(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    wo = get_work_order(id)
    limit, offset = parse_pagination()
    items = [b for b in db.bypass_plans.values() if b["work_order_id"] == wo["id"]]
    st = request.args.get("status")
    if st:
        items = [b for b in items if b["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([bp_view(b) for b in page], limit, offset, total)


@bp.post("/sewer/bypass-plans/<id>/approve")
def approve_bypass(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    b = get_bypass(id)
    if b["status"] != "PROPOSED":
        raise err_invalid_state("bypass not PROPOSED")
    wo = db.work_orders[b["work_order_id"]]
    plan = db.plans[wo["plan_id"]]
    segment = db.segments[plan["segment_id"]]
    # pump sizing (priority 6: flow-control prereq)
    needed = required_pump_gpm(segment["diameter_mm"])
    if b["pump_capacity_gpm"] < needed:
        raise err_conflict("ERR_PUMP_UNDERSIZED", f"requires >= {needed} gpm")
    # window conflict vs other APPROVED/ACTIVE bypasses on same segment
    for other in db.bypass_plans.values():
        if other["id"] == b["id"]:
            continue
        if other["status"] not in ("APPROVED", "ACTIVE"):
            continue
        other_wo = db.work_orders.get(other["work_order_id"])
        if other_wo is None:
            continue
        other_plan = db.plans.get(other_wo["plan_id"])
        if other_plan is None or other_plan["segment_id"] != segment["id"]:
            continue
        if buffered_window_overlap(b["window_start"], b["window_end"], other["window_start"], other["window_end"]):
            raise err_conflict("ERR_BYPASS_WINDOW_CONFLICT", "buffered bypass window overlaps another")
    b["status"] = "APPROVED"
    db.touch(b)
    sweep_notice_expiry()
    return success_object(bp_view(b))


@bp.post("/sewer/bypass-plans/<id>/reject")
def reject_bypass(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    b = get_bypass(id)
    if b["status"] != "PROPOSED":
        raise err_invalid_state("bypass not PROPOSED")
    b["status"] = "REJECTED"
    db.touch(b)
    sweep_notice_expiry()
    return success_object(bp_view(b))


@bp.post("/sewer/bypass-plans/<id>/activate")
def activate_bypass(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    b = get_bypass(id)
    if b["status"] != "APPROVED":
        raise err_invalid_state("bypass not APPROVED")
    technician_capability_check(actor, "CREW_LEAD")
    now = db.now_dt()
    ws = _parse_iso(b["window_start"])
    we = _parse_iso(b["window_end"])
    if not (now >= ws and now < we):
        raise err_conflict("ERR_OUTSIDE_WINDOW", "outside [window_start, window_end)")
    wo = db.work_orders[b["work_order_id"]]
    if wo["execution_status"] not in ("MOBILIZED", "IN_WORK"):
        raise err_invalid_state("work order must be MOBILIZED or IN_WORK to activate bypass")
    b["status"] = "ACTIVE"
    db.touch(b)
    sweep_notice_expiry()
    return success_object(bp_view(b))


@bp.post("/sewer/bypass-plans/<id>/demobilize")
def demobilize_bypass(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    b = get_bypass(id)
    if b["status"] != "ACTIVE":
        raise err_invalid_state("bypass not ACTIVE")
    technician_capability_check(actor, "CREW_LEAD")
    b["status"] = "DEMOBILIZED"
    db.touch(b)
    sweep_notice_expiry()
    return success_object(bp_view(b))


@bp.post("/sewer/bypass-plans/<id>/close")
def close_bypass(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    b = get_bypass(id)
    if b["status"] != "DEMOBILIZED":
        raise err_invalid_state("bypass not DEMOBILIZED")
    b["status"] = "CLOSED"
    db.touch(b)
    sweep_notice_expiry()
    return success_object(bp_view(b))
