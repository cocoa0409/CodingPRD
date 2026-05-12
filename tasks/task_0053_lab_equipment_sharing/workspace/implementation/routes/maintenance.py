"""Maintenance window endpoints."""
from flask import Blueprint, request, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import audit, reservation_ops


bp = Blueprint("maintenance", __name__)


def _get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_BAD_REQUEST", "JSON body required")
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    return body


@bp.post("/equipment/<equipment_id>/maintenance-windows")
@require_auth(roles={"LabOwner"})
def create_maintenance_window(equipment_id):
    eq = db.equipment.get(equipment_id)
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    lab = db.labs.get(eq["lab_id"])
    if lab is None or lab["contact_user_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not the lab owner of this equipment")
    body = _get_body()
    kind = body.get("kind")
    if kind not in ("PERIODIC", "AD_HOC"):
        raise err("ERR_BAD_REQUEST", "kind must be PERIODIC or AD_HOC")
    start_raw = body.get("start_at")
    end_raw = body.get("end_at")
    if not start_raw or not end_raw:
        raise err("ERR_BAD_REQUEST", "start_at and end_at are required")
    try:
        start_at = parse_iso(start_raw)
        end_at = parse_iso(end_raw)
    except ValueError:
        raise err("ERR_BAD_REQUEST", "invalid ISO timestamp")
    if end_at <= start_at:
        raise err("ERR_BAD_REQUEST", "end_at must be > start_at")
    notes = body.get("maintenance_notes", "")
    if not isinstance(notes, str):
        raise err("ERR_BAD_REQUEST", "maintenance_notes must be a string")

    mw = {
        "equipment_id": equipment_id,
        "kind": kind,
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "status": "SCHEDULED",
        "maintenance_notes": notes,
        "acceptance_notes": "",
        "archived_record_uri": None,
    }
    db.stamp_create(mw)
    db.maintenance_windows[mw["id"]] = mw

    # If kind=AD_HOC and start_at <= now < end_at, transition immediately
    if kind == "AD_HOC" and start_at <= now() < end_at:
        if eq["status"] == "AVAILABLE":
            mw["status"] = "IN_PROGRESS"
            db.stamp_update(mw)
            eq["status"] = "MAINTENANCE"
            db.stamp_update(eq)
            overlapping = reservation_ops.find_overlapping_reservations(
                eq["id"], start_at, end_at, statuses=("BOOKED",))
            for r in overlapping:
                reservation_ops.cancel_reservation(
                    r, actor_role="system", actor_user_id="system",
                    refund_bps=10000, reason="ad_hoc_maintenance")
    return success(db.public(mw), status=201)


@bp.post("/maintenance-windows/<window_id>/accept")
@require_auth(roles={"LabOwner", "PlatformAdmin"})
def accept_maintenance(window_id):
    mw = db.maintenance_windows.get(window_id)
    if mw is None:
        raise err("ERR_NOT_FOUND", "maintenance window not found")
    eq = db.equipment.get(mw["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    if g.user_role == "LabOwner":
        lab = db.labs.get(eq["lab_id"])
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    notes = body.get("acceptance_notes", "")
    if not isinstance(notes, str):
        raise err("ERR_BAD_REQUEST", "acceptance_notes must be a string")
    if mw["status"] != "AWAITING_ACCEPTANCE":
        raise err("ERR_INVALID_STATE", "maintenance window not AWAITING_ACCEPTANCE")
    mw["status"] = "ACCEPTED"
    mw["acceptance_notes"] = notes
    mw["archived_record_uri"] = f"archive://maintenance/{mw['id']}"
    db.stamp_update(mw)

    # If no other active maintenance window, equipment back to AVAILABLE
    other_active = any(
        other["id"] != mw["id"] and other["equipment_id"] == eq["id"]
        and other["status"] in ("IN_PROGRESS", "AWAITING_ACCEPTANCE")
        for other in db.maintenance_windows.values()
    )
    if not other_active and eq["status"] == "MAINTENANCE":
        # Certificates must be valid
        if parse_iso(eq["calibration_expires_at"]) > now() and \
           parse_iso(eq["safety_inspection_expires_at"]) > now():
            eq["status"] = "AVAILABLE"
            db.stamp_update(eq)
    return success(db.public(mw))


@bp.post("/maintenance-windows/<window_id>/reject")
@require_auth(roles={"LabOwner", "PlatformAdmin"})
def reject_maintenance(window_id):
    mw = db.maintenance_windows.get(window_id)
    if mw is None:
        raise err("ERR_NOT_FOUND", "maintenance window not found")
    eq = db.equipment.get(mw["equipment_id"])
    if eq is None:
        raise err("ERR_NOT_FOUND", "equipment not found")
    if g.user_role == "LabOwner":
        lab = db.labs.get(eq["lab_id"])
        if lab is None or lab["contact_user_id"] != g.user_id:
            raise err("ERR_FORBIDDEN", "not the lab owner")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "JSON object required")
    notes = body.get("acceptance_notes", "")
    if not isinstance(notes, str):
        raise err("ERR_BAD_REQUEST", "acceptance_notes must be a string")
    if mw["status"] != "AWAITING_ACCEPTANCE":
        raise err("ERR_INVALID_STATE", "maintenance window not AWAITING_ACCEPTANCE")
    mw["status"] = "REJECTED"
    mw["acceptance_notes"] = notes
    db.stamp_update(mw)

    # Spawn follow-up AD_HOC window starting now, ending now+24h
    from datetime import timedelta
    follow_start = now()
    follow_end = follow_start + timedelta(hours=24)
    follow = {
        "equipment_id": eq["id"],
        "kind": "AD_HOC",
        "start_at": iso(follow_start),
        "end_at": iso(follow_end),
        "status": "IN_PROGRESS",
        "maintenance_notes": "follow_up_from_rejection",
        "acceptance_notes": "",
        "archived_record_uri": None,
    }
    db.stamp_create(follow)
    db.maintenance_windows[follow["id"]] = follow
    # Equipment stays in MAINTENANCE (covered by new window)
    if eq["status"] != "MAINTENANCE":
        eq["status"] = "MAINTENANCE"
        db.stamp_update(eq)
    # Cancel overlapping BOOKED reservations for the new window
    overlapping = reservation_ops.find_overlapping_reservations(
        eq["id"], follow_start, follow_end, statuses=("BOOKED",))
    for r in overlapping:
        reservation_ops.cancel_reservation(
            r, actor_role="system", actor_user_id="system",
            refund_bps=10000, reason="follow_up_maintenance")
    return success(db.public(mw))
