"""Yard slot endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require
from response import ok_array, ok_object
from services import serialize
from services.common import (
    get_body,
    optional_bool,
    paginate,
    require_int,
    require_str,
    stamp_create,
)
from services.lookups import fk_slot, path_slot

bp = Blueprint("yard_slots", __name__)


@bp.post("/yard-slots")
@require("YardPlanner", "TerminalAdmin")
def create_slot():
    body = get_body()
    # FK existence (priority 4): below_slot_id, when supplied, must resolve
    below_id = body.get("below_slot_id")
    if below_id is not None:
        if not isinstance(below_id, str):
            raise APIError(ERR_INVALID_REQUEST, 422, "below_slot_id must be a string")
        fk_slot(below_id)
    # shape (priority 5)
    block = require_str(body, "block", non_empty=True)
    bay = require_int(body, "bay")
    if bay < 1:
        raise APIError(ERR_INVALID_REQUEST, 422, "bay must be >= 1")
    row = require_int(body, "row")
    if row < 1:
        raise APIError(ERR_INVALID_REQUEST, 422, "row must be >= 1")
    tier = require_int(body, "tier")
    if tier < 1:
        raise APIError(ERR_INVALID_REQUEST, 422, "tier must be >= 1")
    is_reefer_rack = optional_bool(body, "is_reefer_rack", default=False)

    rec = stamp_create({
        "block": block,
        "bay": bay,
        "row": row,
        "tier": tier,
        "is_reefer_rack": is_reefer_rack,
        "below_slot_id": below_id,
        "occupied_by_container_id": None,
        "status": "EMPTY",
    })
    db.yard_slots[rec["id"]] = rec
    return ok_object(serialize.yard_slot(rec), 201)


@bp.get("/yard-slots/<sid>")
@require("TerminalAdmin", "YardPlanner")
def get_slot(sid):
    rec = path_slot(sid)
    return ok_object(serialize.yard_slot(rec))


@bp.get("/yard-slots")
@require("TerminalAdmin", "YardPlanner")
def list_slots():
    below = request.args.get("below_slot_id")
    occ = request.args.get("occupied_by_container_id")
    rows = list(db.yard_slots.values())
    if below is not None:
        rows = [s for s in rows if s["below_slot_id"] == below]
    if occ is not None:
        rows = [s for s in rows if s["occupied_by_container_id"] == occ]
    items, limit, offset, total = paginate(rows, serialize.yard_slot)
    return ok_array(items, limit, offset, total)
