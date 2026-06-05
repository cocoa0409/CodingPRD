"""Berth window endpoints + lifecycle transitions (PRD §3.2)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_BERTH_CLOSED,
    ERR_BERTH_CONFLICT,
    ERR_BERTH_DRAFT_EXCEEDED,
    ERR_BERTH_LENGTH_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from middleware import require
from response import ok_array, ok_object
from services import serialize
from services.clash import berth_conflict
from services.common import (
    format_dt,
    get_body,
    paginate,
    parse_dt,
    require_present,
    stamp_create,
    touch,
)
from services.lookups import fk_berth, fk_vessel, path_window

bp = Blueprint("berth_windows", __name__)


def _recompute_free_time(window):
    """Cascade: set free_time_expires_at on every container under this window
    to actual_berth_at + vessel.free_time_days days."""
    berthed_at = window["actual_berth_at"]
    if berthed_at is None:
        return
    base = parse_dt(berthed_at)
    for c in db.containers.values():
        if c["berth_window_id"] != window["id"]:
            continue
        vessel = db.vessels.get(c["vessel_id"])
        days = vessel["free_time_days"] if vessel else 0
        expires = base + timedelta(days=days)
        c["free_time_expires_at"] = format_dt(expires)


def _clear_free_time(window):
    for c in db.containers.values():
        if c["berth_window_id"] == window["id"]:
            c["free_time_expires_at"] = None


@bp.post("/berth-windows")
@require("BerthPlanner")
def create_window():
    body = get_body()
    # FK existence (priority 4)
    berth_id = require_present(body, "berth_id")
    if not isinstance(berth_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "berth_id must be a string")
    berth = fk_berth(berth_id)
    vessel_id = require_present(body, "vessel_id")
    if not isinstance(vessel_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "vessel_id must be a string")
    vessel = fk_vessel(vessel_id)
    # shape (priority 5)
    eta = require_present(body, "eta")
    etd = require_present(body, "etd")
    eta_dt = parse_dt(eta)
    etd_dt = parse_dt(etd)
    if not (etd_dt > eta_dt):
        raise APIError(ERR_INVALID_REQUEST, 422, "etd must be strictly after eta")
    # physical fit: draft before length (priority 11, 12)
    if vessel["draft_m"] > berth["draft_m"]:
        raise APIError(ERR_BERTH_DRAFT_EXCEEDED, 409, "vessel draft exceeds berth draft")
    if vessel["loa_m"] > berth["length_m"]:
        raise APIError(ERR_BERTH_LENGTH_EXCEEDED, 409, "vessel LOA exceeds berth length")
    # temporal clash (priority 13)
    conflict = berth_conflict(berth_id, eta, etd, exclude_id=None)
    if conflict is not None:
        raise APIError(ERR_BERTH_CONFLICT, 409, "berth window overlaps an existing window")

    rec = stamp_create({
        "berth_id": berth_id,
        "vessel_id": vessel_id,
        "eta": eta,
        "etd": etd,
        "actual_berth_at": None,
        "actual_depart_at": None,
        "status": "SCHEDULED",
    })
    db.berth_windows[rec["id"]] = rec
    return ok_object(serialize.berth_window(rec), 201)


@bp.get("/berth-windows/<wid>")
@require("TerminalAdmin", "BerthPlanner", "YardPlanner")
def get_window(wid):
    rec = path_window(wid)
    return ok_object(serialize.berth_window(rec))


@bp.get("/berth-windows")
@require("TerminalAdmin", "BerthPlanner", "YardPlanner")
def list_windows():
    vessel_id = request.args.get("vessel_id")
    berth_id = request.args.get("berth_id")
    rows = list(db.berth_windows.values())
    if vessel_id is not None:
        rows = [w for w in rows if w["vessel_id"] == vessel_id]
    if berth_id is not None:
        rows = [w for w in rows if w["berth_id"] == berth_id]
    items, limit, offset, total = paginate(rows, serialize.berth_window)
    return ok_array(items, limit, offset, total)


@bp.post("/berth-windows/<wid>/berth")
@require("BerthPlanner")
def berth_window(wid):
    window = path_window(wid)
    body = get_body()
    # OCC field mandatory on this operation (PRD §2.7)
    expected = require_present(body, "expected_berth_window_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 422, "expected_berth_window_version must be an integer")
    # state (priority 7)
    if window["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "berth window is not SCHEDULED")
    # OCC (priority 18) — evaluated against current version
    if expected != window["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "berth window version is stale")
    # berth availability (priority 14)
    berth = db.berths.get(window["berth_id"])
    if berth is None or berth["status"] != "AVAILABLE":
        raise APIError(ERR_BERTH_CLOSED, 409, "parent berth is not AVAILABLE")
    # one vessel at a time: no other BERTHED window on same berth (priority 13)
    for w in db.berth_windows.values():
        if w["id"] != wid and w["berth_id"] == window["berth_id"] and w["status"] == "BERTHED":
            raise APIError(ERR_BERTH_CONFLICT, 409, "berth already holds a berthed vessel")

    window["actual_berth_at"] = db.clock_now()
    window["status"] = "BERTHED"
    _recompute_free_time(window)
    touch(window)
    return ok_object(serialize.berth_window(window))


@bp.post("/berth-windows/<wid>/unberth")
@require("BerthPlanner")
def unberth_window(wid):
    window = path_window(wid)
    if window["status"] != "BERTHED":
        raise APIError(ERR_INVALID_STATE, 409, "berth window is not BERTHED")
    # cannot rewind if any container under this window has been worked
    for c in db.containers.values():
        if c["berth_window_id"] == wid and c["handling_status"] in ("GROUNDED", "GATED_OUT"):
            raise APIError(ERR_INVALID_STATE, 409, "cargo under this window has already been worked")
    window["actual_berth_at"] = None
    window["status"] = "SCHEDULED"
    _clear_free_time(window)
    touch(window)
    return ok_object(serialize.berth_window(window))


@bp.post("/berth-windows/<wid>/depart")
@require("BerthPlanner")
def depart_window(wid):
    window = path_window(wid)
    if window["status"] != "BERTHED":
        raise APIError(ERR_INVALID_STATE, 409, "berth window is not BERTHED")
    window["actual_depart_at"] = db.clock_now()
    window["status"] = "DEPARTED"
    touch(window)
    return ok_object(serialize.berth_window(window))


@bp.post("/berth-windows/<wid>/cancel")
@require("BerthPlanner")
def cancel_window(wid):
    window = path_window(wid)
    if window["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "berth window is not SCHEDULED")
    window["status"] = "CANCELLED"
    touch(window)
    return ok_object(serialize.berth_window(window))
