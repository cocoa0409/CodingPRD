"""Maintenance window endpoints (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_invalid_time_range, err_window_overlap, err_safety_hold,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_enum, require_datetime, optional_bool,
    parse_pagination, paginate, require_ref, get_window, public_view,
)

bp = Blueprint("windows", __name__)

WINDOW_TYPES = {"SWEEPING", "DRAIN_FLUSH", "LIGHTING_REPAIR", "SEALANT_WORK"}
BUFFER = timedelta(minutes=30)


@bp.post("/ops/maintenance-windows")
def create_window():
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    level = require_string(payload, "level")
    wtype = require_enum(payload, "window_type", WINDOW_TYPES)
    start_at = require_datetime(payload, "start_at")
    end_at = require_datetime(payload, "end_at")
    safety = optional_bool(payload, "safety_authorized", default=False)
    # PRD 3.7 order: time range, then 30-minute buffer overlap, then safety hold
    if end_at <= start_at:
        raise err_invalid_time_range()
    for w in db.maintenance_windows.values():
        if w["facility_id"] != facility["id"] or w["level"] != level:
            continue
        if w["window_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        ex_start = db.parse_iso(w["start_at"])
        ex_end = db.parse_iso(w["end_at"])
        # no conflict iff new.start >= existing.end + 30min or existing.start >= new.end + 30min
        if start_at >= ex_end + BUFFER or ex_start >= end_at + BUFFER:
            continue
        raise err_window_overlap()
    has_critical_on_level = any(
        i["facility_id"] == facility["id"]
        and i["inspection_status"] == "REPORTED"
        and i["condition_class"] == "CRITICAL"
        and i["level_scope"] == level
        for i in db.inspections.values()
    )
    if has_critical_on_level and not safety:
        raise err_safety_hold()
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "level": level,
        "window_type": wtype,
        "start_at": db.format_iso(start_at),
        "end_at": db.format_iso(end_at),
        "safety_authorized": safety,
        "window_status": "SCHEDULED",
    }
    db.stamp_new(ent)
    db.maintenance_windows[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/maintenance-windows/<maintenance_window_id>")
def get_window_route(maintenance_window_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_window(maintenance_window_id)))


@bp.get("/ops/maintenance-windows")
def list_windows():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.maintenance_windows.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("window_status")
    level = request.args.get("level")
    if facility_id is not None:
        items = [w for w in items if w["facility_id"] == facility_id]
    if status is not None:
        items = [w for w in items if w["window_status"] == status]
    if level is not None:
        items = [w for w in items if w["level"] == level]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(w) for w in page], limit, offset, total)


@bp.post("/ops/maintenance-windows/<maintenance_window_id>/start")
def start_window(maintenance_window_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    w = get_window(maintenance_window_id)
    if w["window_status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED window may start")
    w["window_status"] = "IN_PROGRESS"
    db.touch(w)
    return success_object(public_view(w))


@bp.post("/ops/maintenance-windows/<maintenance_window_id>/complete")
def complete_window(maintenance_window_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    w = get_window(maintenance_window_id)
    if w["window_status"] != "IN_PROGRESS":
        raise err_invalid_state("only an IN_PROGRESS window may complete")
    w["window_status"] = "COMPLETED"
    db.touch(w)
    return success_object(public_view(w))


@bp.post("/ops/maintenance-windows/<maintenance_window_id>/cancel")
def cancel_window(maintenance_window_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    w = get_window(maintenance_window_id)
    if w["window_status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED window may be cancelled")
    w["window_status"] = "CANCELLED"
    db.touch(w)
    return success_object(public_view(w))
