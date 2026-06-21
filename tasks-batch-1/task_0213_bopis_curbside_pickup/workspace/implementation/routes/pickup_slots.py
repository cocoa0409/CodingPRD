"""PickupSlot endpoints."""

from flask import Blueprint

from db import db, stamp_common
from errors import err
from middleware import require_auth, get_json_body
from response import object_response
from services.common import require_str, require_pos_int, require_int, ref_or_404, get_or_404, ser_slot
from clock import parse_iso

bp = Blueprint("pickup_slots", __name__)


@bp.post("/pickup-slots")
def create_slot():
    require_auth({"PlatformAdmin", "StoreManager"})
    body = get_json_body()
    store_id = require_str(body, "store_id")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    capacity = require_pos_int(body, "capacity")
    cutoff = 30
    if "cutoff_offset_minutes" in body and body["cutoff_offset_minutes"] is not None:
        cutoff = require_int(body, "cutoff_offset_minutes")
        if cutoff < 0:
            raise err("ERR_INVALID_REQUEST", "cutoff_offset_minutes must be >= 0")

    # parse datetimes
    try:
        ws = parse_iso(window_start_raw)
        we = parse_iso(window_end_raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO-8601")
    if not (we > ws):
        raise err("ERR_INVALID_REQUEST", "window_end must be strictly after window_start")

    # FK existence
    ref_or_404(db.stores, store_id, "store")

    rec = {
        "store_id": store_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "cutoff_offset_minutes": cutoff,
        "capacity": capacity,
        "booked_count": 0,
        "fill_status": "OPEN",
    }
    stamp_common(rec)
    db.pickup_slots[rec["id"]] = rec
    return object_response(ser_slot(rec), 201)


@bp.get("/pickup-slots/<sid>")
def get_slot(sid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.pickup_slots, sid)
    return object_response(ser_slot(rec))
