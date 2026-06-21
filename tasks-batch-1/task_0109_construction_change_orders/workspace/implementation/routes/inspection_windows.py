"""Inspection-window endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INSPECTION_BUFFER_CONFLICT,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("inspection_windows", __name__)


def _get_or_404(iid):
    w = db.inspection_windows.get(iid)
    if w is None:
        raise err(ERR_NOT_FOUND, "InspectionWindow not found.")
    return w


def _gap_seconds(start_a, end_a, start_b, end_b):
    """Gap between two closed intervals [start_a,end_a] and [start_b,end_b].

    If they overlap, the gap is 0. Otherwise it's the distance between the
    nearer endpoints.
    """
    if start_a <= end_b and start_b <= end_a:
        return 0.0
    if end_a < start_b:
        return (start_b - end_a).total_seconds()
    return (start_a - end_b).total_seconds()


@bp.post("/inspection-windows")
def create_inspection_window():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "inspector_name", "scheduled_start", "scheduled_end"])

    project_id = h.as_string(body["project_id"], "project_id")
    if db.projects.get(project_id) is None:
        raise err(ERR_NOT_FOUND, "Project not found.")
    inspector = h.as_string(body["inspector_name"], "inspector_name")
    start_dt = h.parse_datetime(body["scheduled_start"], "scheduled_start")
    end_dt = h.parse_datetime(body["scheduled_end"], "scheduled_end")
    buffer_minutes = 30
    if body.get("buffer_minutes") is not None:
        buffer_minutes = h.as_int(body["buffer_minutes"], "buffer_minutes", allow_negative=False)

    # Field-shape: scheduled_end strictly after scheduled_start (ERR_INVALID_REQUEST).
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_REQUEST, "scheduled_end must be strictly after scheduled_start.")

    # Buffer-overlap (priority 9): closed intervals; conflict iff gap strictly
    # less than buffer_minutes. Compare against non-CANCELLED slots on the project.
    buffer_seconds = buffer_minutes * 60
    for w in db.inspection_windows.values():
        if w["project_id"] != project_id or w["status"] == "CANCELLED":
            continue
        other_start = h.parse_datetime(w["scheduled_start"], "scheduled_start")
        other_end = h.parse_datetime(w["scheduled_end"], "scheduled_end")
        gap = _gap_seconds(start_dt, end_dt, other_start, other_end)
        if gap < buffer_seconds:
            raise err(ERR_INSPECTION_BUFFER_CONFLICT,
                      "Inspection window conflicts with an existing slot's buffer.")

    record = {
        "project_id": project_id,
        "inspector_name": inspector,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "buffer_minutes": buffer_minutes,
        "status": "BOOKED",
    }
    db.stamp_create(record)
    db.inspection_windows[record["id"]] = record
    return success(h.inspection_window_out(record), status=201)


@bp.get("/inspection-windows/<iid>")
def get_inspection_window(iid):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.inspection_window_out(_get_or_404(iid)))


@bp.get("/inspection-windows")
def list_inspection_windows():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.inspection_windows.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.inspection_window_out(r) for r in page], pagination=meta)


@bp.post("/inspection-windows/<iid>/complete")
def complete_inspection_window(iid):
    _uid, role = authenticate()
    require_role(role, {"Architect"})
    w = _get_or_404(iid)
    if w["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "InspectionWindow is not BOOKED.")
    w["status"] = "COMPLETED"
    db.touch(w)
    return success(h.inspection_window_out(w))


@bp.post("/inspection-windows/<iid>/cancel")
def cancel_inspection_window(iid):
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    w = _get_or_404(iid)
    if w["status"] != "BOOKED":
        raise err(ERR_INVALID_STATE, "InspectionWindow is not BOOKED.")
    w["status"] = "CANCELLED"
    db.touch(w)
    return success(h.inspection_window_out(w))
