"""IrrigationEvent endpoints (PRD §3.8).

Overlap geometry: closed intervals with a 6h buffer on each side (stricter
than equipment). SCHEDULED -> COMPLETED (when due) / CANCELLED.
"""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import lookups
import serializers
from errors import err
from helpers import get_json_body, require_number, require_str
from middleware import require_roles
from response import object_response
from timeutil import parse_iso

bp = Blueprint("irrigation_events", __name__)
BUFFER_HOURS = 6


@bp.post("/irrigation-events")
@require_roles("Agronomist")
def create_irrigation():
    body = get_json_body()
    parcel_id = require_str(body, "parcel_id")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    inches_applied = require_number(body, "inches_applied")

    lookups.parcel(parcel_id)

    ws = parse_iso(window_start_raw)
    we = parse_iso(window_end_raw)
    if ws is None or we is None:
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO 8601.")
    if not (we > ws):
        raise err("ERR_VALIDATION_WINDOW_INVALID", "window_end must be after window_start.")
    if inches_applied <= 0:
        raise err("ERR_INVALID_REQUEST", "inches_applied must be > 0.")

    # Closed + 6h buffer overlap on SCHEDULED/COMPLETED events on the parcel
    # (PRD §3.8): new.start <= I.end + BUFFER AND I.start <= new.end + BUFFER.
    buf = timedelta(hours=BUFFER_HOURS)
    for ev in db.irrigation_events.values():
        if ev["parcel_id"] != parcel_id or ev["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        i_start = parse_iso(ev["window_start"])
        i_end = parse_iso(ev["window_end"])
        if ws <= i_end + buf and i_start <= we + buf:
            raise err("ERR_IRRIGATION_WINDOW_CONFLICT", "Irrigation window conflicts.")

    rec = db.new_entity(
        {
            "parcel_id": parcel_id,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "inches_applied": inches_applied,
            "status": "SCHEDULED",
        }
    )
    db.irrigation_events[rec["id"]] = rec
    return object_response(serializers.irrigation_event(rec), 201)


@bp.get("/irrigation-events/<eid>")
@require_roles("FarmManager", "Agronomist")
def get_irrigation(eid):
    rec = lookups.irrigation_event(eid)
    return object_response(serializers.irrigation_event(rec))


@bp.post("/irrigation-events/<eid>/complete")
@require_roles("Agronomist")
def complete_irrigation(eid):
    rec = lookups.irrigation_event(eid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Irrigation event is not SCHEDULED.")
    # Only once current clock >= window_start (PRD §3.8).
    now = clock.now()
    ws = parse_iso(rec["window_start"])
    if ws is not None and now < ws:
        raise err("ERR_IRRIGATION_NOT_DUE", "Irrigation event is not yet due.")
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return object_response(serializers.irrigation_event(rec))


@bp.post("/irrigation-events/<eid>/cancel")
@require_roles("Agronomist")
def cancel_irrigation(eid):
    rec = lookups.irrigation_event(eid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Irrigation event is not SCHEDULED.")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return object_response(serializers.irrigation_event(rec))
