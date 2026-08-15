"""OutageWindow endpoints."""
from flask import Blueprint, request
from datetime import timedelta

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_state_transition, err_segregation_of_duties,
    err_open_critical_defect, err_interval_in_past, err_outage_window_conflict,
    err_outage_needs_revalidation, err_outside_window, err_steps_not_verified,
    err_asset_decommissioned, err_stale_version,
)
from services.common import (
    body, require_string, require_number, parse_datetime_field, parse_pagination,
    paginate, get_substation, get_asset, get_outage_window, dec, round2,
    intervals_overlap,
)
from services.calculations import refresh_asset_condition_and_due

bp = Blueprint("outage_windows", __name__)


def outage_window_view(w):
    return {
        "id": w["id"],
        "substation_id": w["substation_id"],
        "asset_id": w["asset_id"],
        "start_ts": w["start_ts"],
        "end_ts": w["end_ts"],
        "purpose": w["purpose"],
        "status": w["status"],
        "requested_by": w["requested_by"],
        "approved_by": w.get("approved_by"),
        "duration_hours": w.get("duration_hours"),
        "committed_hours": w.get("committed_hours", 0),
        "needs_revalidation": w.get("needs_revalidation", False),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def _check_open_critical_defect(asset_id):
    """Check for C1 defects in OPEN, WORK_ORDERED, DEFERRED on this asset."""
    for d in db.defects.values():
        if d["asset_id"] == asset_id and d["severity"] == "C1" and d["status"] in ("OPEN", "WORK_ORDERED", "DEFERRED"):
            raise err_open_critical_defect()


def _check_outage_conflict(asset_id, start_ts, end_ts, exclude_id=None):
    """Check overlap and 24h buffer against non-terminal windows of the same asset."""
    for w in db.outage_windows.values():
        if w["asset_id"] != asset_id:
            continue
        if w["id"] == exclude_id:
            continue
        if w["status"] not in ("REQUESTED", "APPROVED", "SWITCHING", "CLEARED"):
            continue
        w_start = db._parse_iso(w["start_ts"])
        w_end = db._parse_iso(w["end_ts"])
        # Overlap check
        if intervals_overlap(start_ts, end_ts, w_start, w_end):
            raise err_outage_window_conflict("Outage window overlaps existing window")
        # 24h buffer check: gap between windows must be >= 24h
        if end_ts <= w_start:
            gap = w_start - end_ts
        elif w_end <= start_ts:
            gap = start_ts - w_end
        else:
            gap = timedelta(0)  # overlapping (should not happen due to check above)
        if gap < timedelta(hours=24):
            raise err_outage_window_conflict("Outage window violates 24-hour buffer")


@bp.post("/outage-windows")
def create_outage_window():
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    payload = body()
    substation_id = require_string(payload, "substation_id")
    asset_id = require_string(payload, "asset_id")
    start_ts = parse_datetime_field(payload, "start_ts", required=True)
    end_ts = parse_datetime_field(payload, "end_ts", required=True)
    purpose = require_string(payload, "purpose")

    # Validate end > start
    if end_ts <= start_ts:
        raise err_validation("end_ts must be strictly after start_ts")

    # FK checks
    get_substation(substation_id)
    asset = get_asset(asset_id)

    # Decommissioned asset guard
    if asset["status"] == "DECOMMISSIONED":
        raise err_asset_decommissioned()

    # Open critical defect check
    _check_open_critical_defect(asset_id)

    # Interval in past check
    now = db.now_dt()
    if start_ts <= now:
        raise err_interval_in_past()

    # Conflict check (overlap + 24h buffer)
    _check_outage_conflict(asset_id, start_ts, end_ts)

    # Compute duration_hours
    duration = (end_ts - start_ts).total_seconds() / 3600.0
    duration_hours = round2(duration)

    ent = {
        "id": db.new_id(),
        "substation_id": substation_id,
        "asset_id": asset_id,
        "start_ts": db._format_iso(start_ts),
        "end_ts": db._format_iso(end_ts),
        "purpose": purpose,
        "status": "REQUESTED",
        "requested_by": actor.user_id,
        "approved_by": None,
        "duration_hours": duration_hours,
        "committed_hours": 0,
        "needs_revalidation": False,
    }
    db.stamp_new(ent)
    db.outage_windows[ent["id"]] = ent
    return success_object(outage_window_view(ent), status=201)


@bp.get("/outage-windows")
def list_outage_windows():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.outage_windows.values())
    substation_id = request.args.get("substation_id")
    if substation_id:
        items = [w for w in items if w["substation_id"] == substation_id]
    asset_id = request.args.get("asset_id")
    if asset_id:
        items = [w for w in items if w["asset_id"] == asset_id]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([outage_window_view(w) for w in page], limit, offset, total)


@bp.get("/outage-windows/<id>")
def get_outage_window_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    w = get_outage_window(id)
    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/approve")
def approve_outage_window(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    w = get_outage_window(id)
    # State check
    if w["status"] != "REQUESTED":
        raise err_state_transition("Window is not REQUESTED")
    # Segregation of duties
    if actor.user_id == w["requested_by"]:
        raise err_segregation_of_duties("Approver must differ from requester")
    # Needs revalidation check
    if w.get("needs_revalidation", False):
        raise err_outage_needs_revalidation()
    # Open critical defect check
    _check_open_critical_defect(w["asset_id"])

    w["status"] = "APPROVED"
    w["approved_by"] = actor.user_id
    db.touch(w)

    # Add duration_hours to asset's approved_outage_hours
    asset = db.assets[w["asset_id"]]
    asset["approved_outage_hours"] = asset.get("approved_outage_hours", 0) + w["duration_hours"]
    db.touch(asset)

    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/reject")
def reject_outage_window(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    w = get_outage_window(id)
    if w["status"] != "REQUESTED":
        raise err_state_transition("Window is not REQUESTED")
    w["status"] = "REJECTED"
    db.touch(w)
    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/cancel")
def cancel_outage_window(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    w = get_outage_window(id)
    if w["status"] not in ("REQUESTED", "APPROVED"):
        raise err_state_transition("Window is not REQUESTED or APPROVED")

    was_approved = w["status"] == "APPROVED"
    w["status"] = "CANCELLED"
    db.touch(w)

    if was_approved:
        # Compensate: subtract duration from asset's approved_outage_hours
        asset = db.assets[w["asset_id"]]
        asset["approved_outage_hours"] = asset.get("approved_outage_hours", 0) - w["duration_hours"]
        db.touch(asset)

        # Cancel linked work orders in DRAFT or SCHEDULED
        for wo in db.work_orders.values():
            if wo.get("outage_window_id") == w["id"] and wo["status"] in ("DRAFT", "SCHEDULED"):
                if wo["status"] == "SCHEDULED":
                    w["committed_hours"] = w.get("committed_hours", 0) - wo["estimated_hours"]
                wo["status"] = "CANCELLED"
                db.touch(wo)
                # Return defect to OPEN
                defect = db.defects.get(wo["defect_id"])
                if defect and defect["status"] == "WORK_ORDERED":
                    defect["status"] = "OPEN"
                    db.touch(defect)

    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/begin-switching")
def begin_switching(id):
    actor = get_actor()
    require_roles(actor, ["SwitchingSupervisor"])
    w = get_outage_window(id)
    if w["status"] != "APPROVED":
        raise err_state_transition("Window is not APPROVED")
    if w.get("needs_revalidation", False):
        raise err_outage_needs_revalidation()
    now = db.now_dt()
    start = db._parse_iso(w["start_ts"])
    end = db._parse_iso(w["end_ts"])
    if not (start <= now < end):
        raise err_outside_window()
    # Must have at least one switching step
    has_steps = any(s["outage_window_id"] == id for s in db.switching_steps.values())
    if not has_steps:
        raise err_state_transition("Window has no switching steps")

    w["status"] = "SWITCHING"
    db.touch(w)

    # Asset -> OUT_OF_SERVICE
    asset = db.assets[w["asset_id"]]
    if asset["status"] == "IN_SERVICE":
        asset["status"] = "OUT_OF_SERVICE"
        db.touch(asset)

    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/clear")
def clear_outage_window(id):
    actor = get_actor()
    require_roles(actor, ["SwitchingSupervisor"])
    w = get_outage_window(id)
    if w["status"] != "SWITCHING":
        raise err_state_transition("Window is not SWITCHING")
    # Every switching step must be VERIFIED
    for s in db.switching_steps.values():
        if s["outage_window_id"] == id and s["status"] != "VERIFIED":
            raise err_steps_not_verified()
    w["status"] = "CLEARED"
    db.touch(w)
    return success_object(outage_window_view(w))


@bp.post("/outage-windows/<id>/restore")
def restore_outage_window(id):
    actor = get_actor()
    require_roles(actor, ["SwitchingSupervisor"])
    w = get_outage_window(id)
    if w["status"] != "CLEARED":
        raise err_state_transition("Window is not CLEARED")
    # No work order linked to this window in SCHEDULED or IN_PROGRESS
    for wo in db.work_orders.values():
        if wo.get("outage_window_id") == id and wo["status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise err_state_transition("Work orders still SCHEDULED or IN_PROGRESS")
    w["status"] = "RESTORED"
    db.touch(w)

    # Asset -> IN_SERVICE
    asset = db.assets[w["asset_id"]]
    if asset["status"] == "OUT_OF_SERVICE":
        asset["status"] = "IN_SERVICE"
        db.touch(asset)

    return success_object(outage_window_view(w))
