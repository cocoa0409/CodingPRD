"""Vessel endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE, ERR_INVALID_REQUEST
from middleware import require
from response import ok_array, ok_object
from services import serialize
from services.common import (
    IMO_RE,
    get_body,
    paginate,
    require_int,
    require_number,
    require_str,
    stamp_create,
)
from services.lookups import path_vessel

bp = Blueprint("vessels", __name__)


@bp.post("/vessels")
@require("TerminalAdmin")
def create_vessel():
    body = get_body()
    # shape (priority 5)
    imo = require_str(body, "imo_number", non_empty=True)
    if not IMO_RE.match(imo):
        raise APIError(ERR_INVALID_REQUEST, 422, "imo_number must be exactly 7 digits")
    name = require_str(body, "name", non_empty=True)
    loa_m = require_int(body, "loa_m")
    if loa_m < 50:
        raise APIError(ERR_INVALID_REQUEST, 422, "loa_m must be >= 50")
    draft_m = require_number(body, "draft_m")
    if draft_m <= 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "draft_m must be > 0")
    free_time_days = body.get("free_time_days", 5)
    if free_time_days is None:
        free_time_days = 5
    if isinstance(free_time_days, bool) or not isinstance(free_time_days, int):
        raise APIError(ERR_INVALID_REQUEST, 422, "free_time_days must be an integer")
    if free_time_days < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "free_time_days must be >= 0")
    # uniqueness (priority 6)
    if any(v["imo_number"] == imo for v in db.vessels.values()):
        raise APIError(ERR_DUPLICATE, 409, f"imo_number already exists: {imo}")

    rec = stamp_create({
        "imo_number": imo,
        "name": name,
        "loa_m": loa_m,
        "draft_m": draft_m,
        "free_time_days": free_time_days,
    })
    db.vessels[rec["id"]] = rec
    return ok_object(serialize.vessel(rec), 201)


@bp.get("/vessels/<vid>")
@require("TerminalAdmin", "BerthPlanner", "YardPlanner")
def get_vessel(vid):
    rec = path_vessel(vid)
    return ok_object(serialize.vessel(rec))


@bp.get("/vessels/<vid>/containers")
@require("TerminalAdmin", "YardPlanner", "GateOperator")
def list_vessel_containers(vid):
    path_vessel(vid)
    rows = [c for c in db.containers.values() if c["vessel_id"] == vid]
    items, limit, offset, total = paginate(rows, serialize.container)
    return ok_array(items, limit, offset, total)
