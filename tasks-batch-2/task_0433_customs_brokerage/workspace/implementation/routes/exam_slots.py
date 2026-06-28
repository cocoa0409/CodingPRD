"""Examination slot endpoints (PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_str, require_enum, stamp_create, bump_version,
    lookup, list_response, parse_iso8601,
)
from middleware import require_roles
from response import object_response
from serializers import exam_slot_view

bp = Blueprint("exam_slots", __name__)

STATIONS = {"CES_LAX", "CES_JFK"}


@bp.post("/exam-slots")
@require_roles("CBPOfficer")
def create_slot():
    body = get_body()
    station_code = require_enum(body, "station_code", STATIONS)
    entry_id = body.get("entry_id")
    if not isinstance(entry_id, str) or entry_id == "":
        raise err("ERR_VALIDATION", "entry_id is required.")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    window_start = parse_iso8601(window_start_raw, "window_start")
    window_end = parse_iso8601(window_end_raw, "window_end")

    # existence (404).
    entry = lookup(db.entries, entry_id)

    # ERR_INVALID_EXAM_WINDOW (422): entry must be HOLD_EXAM AND
    # window_end strictly after window_start.
    if entry["status"] != "HOLD_EXAM" or not (window_end > window_start):
        raise err("ERR_INVALID_EXAM_WINDOW", "Entry must be HOLD_EXAM and window_end > window_start.")

    # Overlap with any BOOKED slot on the SAME station (half-open intervals).
    for slot in db.exam_slots.values():
        if slot["station_code"] != station_code or slot["status"] != "BOOKED":
            continue
        existing_start = parse_iso8601(slot["window_start"], "window_start")
        existing_end = parse_iso8601(slot["window_end"], "window_end")
        # overlap = (a.start < b.end) AND (b.start < a.end)
        if window_start < existing_end and existing_start < window_end:
            raise err("ERR_EXAM_SLOT_OVERLAP", "Slot overlaps a BOOKED slot on the same station.")

    rec = {
        "station_code": station_code,
        "entry_id": entry_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "BOOKED",
    }
    stamp_create(rec)
    db.exam_slots[rec["id"]] = rec
    return object_response(exam_slot_view(rec), status=201)


@bp.get("/exam-slots/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_slot(id):
    return object_response(exam_slot_view(lookup(db.exam_slots, id)))


@bp.get("/exam-slots")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_slots():
    return list_response(
        db.exam_slots.values(), exam_slot_view,
        filters=[("entry_id", "entry_id"), ("station_code", "station_code")],
    )


@bp.post("/exam-slots/<id>/cancel")
@require_roles("CBPOfficer")
def cancel_slot(id):
    slot = lookup(db.exam_slots, id)
    if slot["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Slot is not BOOKED.")
    slot["status"] = "CANCELLED_SLOT"
    bump_version(slot)
    return object_response(exam_slot_view(slot))
