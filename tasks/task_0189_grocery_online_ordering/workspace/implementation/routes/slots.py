"""FulfillmentSlot endpoints (PRD §2.6 / §2.7 / §3.1, SCAFFOLD §1.5)."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_SLOT_NOT_FOUND, ERR_STORE_NOT_FOUND, ERR_VALIDATION,
    ERR_SLOT_WINDOW_OVERLAP, ERR_INVALID_ORDER_STATE,
)
from middleware import get_user_context, require_role
import validate as V
from timeutil import parse_iso
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("slots", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end): overlap iff a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


@bp.route("/v1/slots", methods=["POST"])
def create_slot():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    body = V.get_body()
    store_id = V.require_str(body, "store_id")
    slot_type = V.require_enum(body, "slot_type", {"DELIVERY", "PICKUP"})
    window_start_raw = V.require_str(body, "window_start")
    window_end_raw = V.require_str(body, "window_end")
    capacity = V.require_int(body, "capacity", minimum=1)  # must be >= 1
    try:
        ws = parse_iso(window_start_raw)
        we = parse_iso(window_end_raw)
    except ValueError:
        err(ERR_VALIDATION, "window_start/window_end must be ISO 8601 instants")
    # window_end must be strictly after window_start (PRD §2.7).
    if not (we > ws):
        err(ERR_VALIDATION, "window_end must be strictly after window_start")
    with db.lock:
        if store_id not in db.stores:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        # Non-overlap with existing slot of same store + slot_type (PRD §2.7).
        for existing in db.slots.values():
            if existing["store_id"] != store_id or existing["slot_type"] != slot_type:
                continue
            es = parse_iso(existing["window_start"])
            ee = parse_iso(existing["window_end"])
            if _windows_overlap(ws, we, es, ee):
                err(ERR_SLOT_WINDOW_OVERLAP, "New slot window overlaps an existing slot")
        slot = {
            "store_id": store_id,
            "slot_type": slot_type,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "capacity": capacity,
            "booked_count": 0,   # PRD §3.1: freshly created with booked_count 0
            "status": "OPEN",    # PRD §3.1: opens with status OPEN
        }
        db.stamp_create(slot)
        db.slots[slot["id"]] = slot
        return object_response(public(slot), 201)


@bp.route("/v1/slots", methods=["GET"])
def list_slots():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    limit, offset = get_pagination()
    store_id = request.args.get("store_id")
    slot_type = request.args.get("slot_type")
    with db.lock:
        records = list(db.slots.values())
        if store_id is not None:
            records = [s for s in records if s["store_id"] == store_id]
        if slot_type is not None:
            records = [s for s in records if s["slot_type"] == slot_type]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer"})  # PRD §4
    with db.lock:
        slot = db.slots.get(slot_id)
        if slot is None:
            err(ERR_SLOT_NOT_FOUND, "Slot not found")
        return object_response(public(slot))


@bp.route("/v1/slots/<slot_id>/close", methods=["POST"])
def close_slot(slot_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps"})  # PRD §4
    with db.lock:
        slot = db.slots.get(slot_id)
        if slot is None:
            err(ERR_SLOT_NOT_FOUND, "Slot not found")
        # Closeable from OPEN or FULL (state machine FulfillmentSlot).
        if slot["status"] not in ("OPEN", "FULL"):
            err(ERR_INVALID_ORDER_STATE, "Slot cannot be closed from its current state")
        slot["status"] = "CLOSED"
        db.touch(slot)
        return object_response(public(slot))
