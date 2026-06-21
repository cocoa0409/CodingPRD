"""Berth endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE
from middleware import require
from response import ok_array, ok_object
from services import serialize
from services.common import (
    get_body,
    paginate,
    require_int,
    require_number,
    require_str,
    stamp_create,
)
from services.lookups import path_berth

bp = Blueprint("berths", __name__)


@bp.post("/berths")
@require("TerminalAdmin")
def create_berth():
    body = get_body()
    # shape (priority 5)
    code = require_str(body, "code", non_empty=True)
    length_m = require_int(body, "length_m")
    if length_m < 50:
        raise APIError("ERR_INVALID_REQUEST", 422, "length_m must be >= 50")
    draft_m = require_number(body, "draft_m")
    if draft_m <= 0:
        raise APIError("ERR_INVALID_REQUEST", 422, "draft_m must be > 0")
    status = body.get("status", "AVAILABLE")
    if status is None:
        status = "AVAILABLE"
    if status not in ("AVAILABLE", "CLOSED"):
        raise APIError("ERR_INVALID_REQUEST", 422, "status must be one of {AVAILABLE, CLOSED}")
    # uniqueness (priority 6)
    if any(b["code"] == code for b in db.berths.values()):
        raise APIError(ERR_DUPLICATE, 409, f"berth code already exists: {code}")

    rec = stamp_create({
        "code": code,
        "length_m": length_m,
        "draft_m": draft_m,
        "status": status,
    })
    db.berths[rec["id"]] = rec
    return ok_object(serialize.berth(rec), 201)


@bp.get("/berths/<bid>")
@require("TerminalAdmin", "BerthPlanner")
def get_berth(bid):
    rec = path_berth(bid)
    return ok_object(serialize.berth(rec))


@bp.get("/berths")
@require("TerminalAdmin", "BerthPlanner")
def list_berths():
    items, limit, offset, total = paginate(list(db.berths.values()), serialize.berth)
    return ok_array(items, limit, offset, total)


@bp.get("/berths/<bid>/berth-windows")
@require("TerminalAdmin", "BerthPlanner")
def list_berth_windows_for_berth(bid):
    path_berth(bid)
    rows = [w for w in db.berth_windows.values() if w["berth_id"] == bid]
    items, limit, offset, total = paginate(rows, serialize.berth_window)
    return ok_array(items, limit, offset, total)
