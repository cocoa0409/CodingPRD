"""TestEvent endpoints (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint, request

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
    TEST_TYPES,
    bad,
    get_station,
    get_test_event,
    json_body,
    req_datetime,
    req_enum,
    req_string,
)

bp = Blueprint("test_events", __name__)


@bp.post("/test-events")
@guard("ComplianceAdmin")
def create_test_event():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    test_type = req_enum(body, "test_type", TEST_TYPES)
    window_start_at = req_datetime(body, "window_start_at")
    window_end_at = req_datetime(body, "window_end_at")
    if not window_start_at < window_end_at:
        bad("Field 'window_start_at' must be strictly earlier than 'window_end_at'.")

    station = get_station(station_id)

    # rung 8 — posture safety
    if station["compliance_posture"] == "SUSPENDED_FILINGS":
        raise ApiError("ERR_POSTURE_NOT_TEST_ELIGIBLE")

    # rung 10 — clock-relative windows
    now = clock.now()
    if window_start_at < now:
        raise ApiError("ERR_TEST_WINDOW_IN_PAST")
    for other in store.test_events_of_station(station_id):
        if other["status"] == "FAILED_UNFILED":
            continue
        # both intervals half-open: touching endpoints do not overlap
        if window_start_at < other["window_end_at"] and other["window_start_at"] < window_end_at:
            raise ApiError("ERR_TEST_WINDOW_OVERLAP")

    event = base_row()
    event.update({
        "station_id": station_id,
        "test_type": test_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "status": "SCHEDULED",
        "readiness_score": None,
        "readiness_evaluated_at": None,
        "filing_deadline_at": window_end_at + timedelta(days=calc.FILING_DUE_DAYS),
        "logged_entry_count": 0,
        "retention_until_max": None,
    })
    db.test_events[event["id"]] = event
    mark_created(event)
    return object_response(serializers.test_event(event), 201)


@bp.get("/test-events/<event_id>")
@guard(*ANY_ROLE)
def read_test_event(event_id):
    event = get_test_event(event_id)
    return object_response(serializers.test_event(event))


@bp.get("/test-events")
@guard(*ANY_ROLE)
def list_test_events():
    rows = list(db.test_events.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("test_type", "test_type"),
        ("status", "status"),
    ))
    return collection_response(rows, request, serializers.test_event)


@bp.post("/test-events/<event_id>/evaluate-readiness")
@guard("StationEngineer")
def evaluate_readiness(event_id):
    event = get_test_event(event_id)
    station = db.stations.get(event["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 7 — state
    if event["status"] not in ("SCHEDULED", "READINESS_PENDING"):
        raise ApiError("ERR_TEST_NOT_READY")

    # rung 10 — the readiness window opens 24h before the start bound
    now = clock.now()
    opens_at = event["window_start_at"] - timedelta(hours=calc.PREFLIGHT_HOURS)
    if now < opens_at or now > event["window_end_at"]:
        raise ApiError("ERR_READINESS_WINDOW_NOT_OPEN")

    plan = db.state_plans.get(station["state_plan_id"]) if station is not None else None
    score = calc.test_event_readiness_score(station, plan)
    event["readiness_score"] = score
    event["readiness_evaluated_at"] = now
    event["status"] = "READY" if score >= calc.READINESS_PASS_MIN else "READINESS_PENDING"
    touch(event)
    return object_response(serializers.test_event(event))


@bp.post("/test-events/<event_id>/close-logging")
@guard("StationEngineer")
def close_logging(event_id):
    event = get_test_event(event_id)
    station = db.stations.get(event["station_id"])
    if station is not None:
        check_station_ownership(station)

    if event["status"] != "READY":
        raise ApiError("ERR_TEST_NOT_READY")
    if event["logged_entry_count"] == 0:
        raise ApiError("ERR_TEST_NO_ENTRIES")

    event["status"] = "LOGGED"
    entries = store.log_entries_of_event(event["id"])
    retention_values = [e["retention_until"] for e in entries if e["retention_until"] is not None]
    event["retention_until_max"] = max(retention_values) if retention_values else None
    touch(event)
    return object_response(serializers.test_event(event))
