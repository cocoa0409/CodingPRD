"""TestLogEntry endpoints (PRD 3.6).

Log lines are append-only and immutable: they expose only id and created_at
among the audit fields and carry no status of their own.
"""

from flask import Blueprint, g, request

import clock
import serializers
import store
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import calculations as calc
from store import base_row, db, mark_created, touch
from validators import (
    ENTRY_KINDS,
    bad,
    get_device,
    get_log_entry,
    get_test_event,
    json_body,
    present,
    req_enum,
    req_string,
)

bp = Blueprint("log_entries", __name__)


@bp.post("/test-log-entries")
@guard("StationEngineer")
def create_log_entry():
    body = json_body(request)
    test_event_id = req_string(body, "test_event_id")
    device_id = req_string(body, "device_id")
    entry_kind = req_enum(body, "entry_kind", ENTRY_KINDS)
    if entry_kind == "RECEIPT":
        source_call_sign = req_string(body, "source_call_sign")
    else:
        if present(body, "source_call_sign"):
            bad("Field 'source_call_sign' must be absent on a TRANSMISSION line.")
        source_call_sign = None

    # rung 4 — test_event_id then device_id
    event = get_test_event(test_event_id)
    device = get_device(device_id)

    station = db.stations.get(event["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 7 — state
    if event["status"] != "READY":
        raise ApiError("ERR_TEST_NOT_READY")

    # rung 9 — cross-row referential coherence (source first, then device)
    matching = []
    if entry_kind == "RECEIPT":
        matching = [
            a for a in store.assignments_of_station(event["station_id"])
            if a["source_call_sign"] == source_call_sign
        ]
        if not matching:
            raise ApiError("ERR_LOG_ENTRY_SOURCE_UNKNOWN")
    if device["station_id"] != event["station_id"]:
        raise ApiError("ERR_DEVICE_STATION_MISMATCH")

    # rung 10 — the logging window is CLOSED at both ends
    now = clock.now()
    if now < event["window_start_at"] or now > event["window_end_at"]:
        raise ApiError("ERR_LOGGING_WINDOW_CLOSED")

    retention_days_applied, retention_until = calc.retention_for(event, station, now)

    entry = base_row(versioned=False)
    entry.update({
        "test_event_id": test_event_id,
        "device_id": device_id,
        "entry_kind": entry_kind,
        "source_call_sign": source_call_sign,
        "logged_at": now,
        "logged_by_user_id": g.user_id,
        "retention_days_applied": retention_days_applied,
        "retention_until": retention_until,
    })
    db.log_entries[entry["id"]] = entry
    mark_created(entry)

    event["logged_entry_count"] += 1
    touch(event)

    # a RECEIPT line doubles as a monitored-source receipt
    for assignment in matching:
        assignment["last_receipt_at"] = now
        if assignment["status"] == "SILENT":
            assignment["status"] = "ACTIVE"
            assignment["silence_flagged_at"] = None
        touch(assignment)

    return object_response(serializers.log_entry(entry), 201)


@bp.get("/test-log-entries/<entry_id>")
@guard(*ANY_ROLE)
def read_log_entry(entry_id):
    entry = get_log_entry(entry_id)
    return object_response(serializers.log_entry(entry))


@bp.get("/test-log-entries")
@guard(*ANY_ROLE)
def list_log_entries():
    rows = list(db.log_entries.values())
    rows = filter_equals(rows, request, (
        ("test_event_id", "test_event_id"),
        ("device_id", "device_id"),
        ("entry_kind", "entry_kind"),
        ("source_call_sign", "source_call_sign"),
    ))
    return collection_response(rows, request, serializers.log_entry)
