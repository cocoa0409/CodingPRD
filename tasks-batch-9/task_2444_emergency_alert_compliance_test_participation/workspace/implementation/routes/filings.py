"""FilingRecord endpoints (PRD 3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import clock
import serializers
import store
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import calculations as calc
from services import scoring
from store import base_row, db, mark_created, touch
from validators import (
    get_filing,
    get_test_event,
    json_body,
    req_int,
    req_string,
)

bp = Blueprint("filings", __name__)

LIVE_FILING_STATES = ("SUBMITTED", "ACCEPTED")


@bp.post("/filing-records")
@guard("CertifyingOfficer")
def create_filing():
    body = json_body(request)
    test_event_id = req_string(body, "test_event_id")
    expected_test_event_version = req_int(body, "expected_test_event_version")
    attestation_note = req_string(body, "attestation_note")

    event = get_test_event(test_event_id)
    station = db.stations.get(event["station_id"])
    if station is not None:
        check_station_ownership(station)

    # rung 6 — optimistic concurrency
    if expected_test_event_version != event["version"]:
        raise ApiError("ERR_STALE_TEST_EVENT_VERSION")

    # rung 7 — state
    if event["status"] == "FAILED_UNFILED":
        raise ApiError("ERR_TEST_ALREADY_FAILED_UNFILED")
    if event["status"] not in ("LOGGED", "FILED"):
        raise ApiError("ERR_TEST_NOT_LOGGED")

    # rung 8 — posture safety
    if station is not None and station["compliance_posture"] == "SUSPENDED_FILINGS":
        raise ApiError("ERR_FILINGS_SUSPENDED")

    # rung 9 — every required source type needs at least one RECEIPT line
    entries = store.log_entries_of_event(event["id"])
    plan = db.state_plans.get(station["state_plan_id"]) if station is not None else None
    required_source_types = list(plan["required_source_types"]) if plan else []
    if required_source_types:
        receipt_call_signs = {
            e["source_call_sign"] for e in entries if e["entry_kind"] == "RECEIPT"
        }
        covered = set()
        for a in store.assignments_of_station(event["station_id"]):
            if a["source_call_sign"] in receipt_call_signs:
                covered.add(a["source_type"])
        for source_type in required_source_types:
            if source_type not in covered:
                raise ApiError("ERR_RECEIPT_COVERAGE_INCOMPLETE")

    # rung 10 — the filing deadline carries a ten-day grace period
    now = clock.now()
    if now > event["filing_deadline_at"] + timedelta(days=calc.FILING_GRACE_DAYS):
        raise ApiError("ERR_FILING_DEADLINE_PASSED")

    # rung 11 — segregation of duties
    for entry in entries:
        if entry["logged_by_user_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # rung 12 — the fiscal ceiling, the very last thing that can stop a filing
    figures = calc.filing_penalty_points(event, event["station_id"], now)
    existing_total = station["penalty_points_total"] if station is not None else Decimal("0.00")
    if calc.r2(Decimal(existing_total) + figures["penalty_points"]) > calc.STATION_POINT_CEILING:
        raise ApiError("ERR_PENALTY_CEILING_EXCEEDED")

    filing = base_row()
    filing.update({
        "test_event_id": test_event_id,
        "attestation_note": attestation_note,
        "filed_at": now,
        "filed_by_user_id": g.user_id,
        "late_days": figures["late_days"],
        "entry_subtotal_points": figures["entry_subtotal_points"],
        "lateness_points": figures["lateness_points"],
        "unconfirmed_relay_points": figures["unconfirmed_relay_points"],
        "penalty_points": figures["penalty_points"],
        "status": "SUBMITTED",
        "reversal_reason": None,
        "superseded_filing_id": None,
    })

    # an amendment reverses whichever earlier filing is still live
    superseded_id = None
    for other in store.filings_of_event(event["id"]):
        if other["status"] in LIVE_FILING_STATES:
            other["status"] = "REVERSED"
            other["reversal_reason"] = "SUPERSEDED_BY_AMENDMENT"
            touch(other)
            superseded_id = other["id"]
    filing["superseded_filing_id"] = superseded_id

    db.filings[filing["id"]] = filing
    mark_created(filing)

    event["status"] = "FILED"
    touch(event)

    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.filing(filing), 201)


@bp.get("/filing-records/<filing_id>")
@guard(*ANY_ROLE)
def read_filing(filing_id):
    filing = get_filing(filing_id)
    return object_response(serializers.filing(filing))


@bp.get("/filing-records")
@guard(*ANY_ROLE)
def list_filings():
    rows = list(db.filings.values())
    rows = filter_equals(rows, request, (
        ("test_event_id", "test_event_id"),
        ("status", "status"),
        ("superseded_filing_id", "superseded_filing_id"),
    ))
    return collection_response(rows, request, serializers.filing)


@bp.post("/filing-records/<filing_id>/accept")
@guard("ComplianceAdmin")
def accept_filing(filing_id):
    filing = get_filing(filing_id)
    if filing["status"] != "SUBMITTED":
        raise ApiError("ERR_FILING_NOT_SUBMITTED")

    filing["status"] = "ACCEPTED"
    touch(filing)

    station = _station_of(filing)
    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.filing(filing))


@bp.post("/filing-records/<filing_id>/reverse")
@guard("ComplianceAdmin")
def reverse_filing(filing_id):
    body = json_body(request)
    reversal_reason = req_string(body, "reversal_reason")

    filing = get_filing(filing_id)
    if filing["status"] not in LIVE_FILING_STATES:
        raise ApiError("ERR_FILING_NOT_REVERSIBLE")

    filing["status"] = "REVERSED"
    filing["reversal_reason"] = reversal_reason
    touch(filing)

    station = _station_of(filing)
    if station is not None:
        scoring.recompute_station(station)
    return object_response(serializers.filing(filing))


def _station_of(filing):
    event = db.test_events.get(filing["test_event_id"])
    if event is None:
        return None
    return db.stations.get(event["station_id"])
