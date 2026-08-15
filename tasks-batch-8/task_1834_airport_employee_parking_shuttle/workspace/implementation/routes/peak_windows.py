"""PeakWindow endpoints."""
from flask import Blueprint, request

import db
from db import parse_dt, touch
from domain import get_or_404, serialize_peak_window
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("peak_windows", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


@bp.route("/parking/peak-windows", methods=["POST"])
def create_peak_window():
    require_roles("ParkingAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("lot_id", "starts_at", "ends_at"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    lot = get_or_404(db.lots, body["lot_id"])
    starts = parse_dt(body["starts_at"])
    ends = parse_dt(body["ends_at"])
    if starts is None or ends is None:
        raise_error("ERR_INVALID_REQUEST", "starts_at/ends_at must be valid ISO datetimes")
    if ends <= starts:
        raise_error("ERR_INVALID_REQUEST", "ends_at must be strictly later than starts_at")
    if lot["tier"] != "REMOTE":
        raise_error("ERR_REMOTE_LOT_REQUIRED", "Peak window target lot must be tier REMOTE")
    # half-open [starts_at, ends_at) overlap among non-CANCELLED windows of the lot;
    # adjacency (starts_at == other.ends_at) is allowed
    for w in db.peak_windows.values():
        if w["lot_id"] == lot["id"] and w["status"] != "CANCELLED":
            ws = parse_dt(w["starts_at"])
            we = parse_dt(w["ends_at"])
            if starts < we and ends > ws:
                raise_error("ERR_PEAK_WINDOW_OVERLAP",
                            "New window overlaps a non-CANCELLED window of the same lot")
    rec = db.new_record({
        "lot_id": lot["id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "status": "SCHEDULED",
    })
    db.peak_windows[rec["id"]] = rec
    return success_object(serialize_peak_window(rec), 201)


@bp.route("/parking/peak-windows/<wid>", methods=["GET"])
def get_peak_window(wid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.peak_windows, wid)
    return success_object(serialize_peak_window(rec), 200)


@bp.route("/parking/peak-windows", methods=["GET"])
def list_peak_windows():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    items = sorted(db.peak_windows.values(), key=lambda w: w["created_at"])
    out = []
    for w in items:
        if lot_id is not None and w["lot_id"] != lot_id:
            continue
        if status is not None and w["status"] != status:
            continue
        out.append(serialize_peak_window(w))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/peak-windows/<wid>/cancel", methods=["POST"])
def cancel_peak_window(wid):
    require_roles("ParkingAdmin")
    rec = get_or_404(db.peak_windows, wid)
    if rec["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Cancel requires the window to be SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize_peak_window(rec), 200)
