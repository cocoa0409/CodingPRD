"""Flight creation, multi-source quorum and cause classification (PRD §2.7,
§3.2).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    FlightStatus,
    create_insurer,
    create_flight,
    create_flight_payload,
    flight_event_payload,
    advance_clock_to,
    advance_clock_by,
    ingest_event,
    finalize_flight_landed,
    finalize_flight_cancelled,
    get_flight,
    setup_flight_with_delay,
    assert_flight,
    assert_flight_status_event,
    QUORUM_WINDOW_MS,
    unique_source_event_id,
)


# ---------------------------------------------------------------------------
# Flight creation
# ---------------------------------------------------------------------------

class TestFlightCreation:
    def test_new_flight_status_scheduled(self, api):
        """PRD §3.2: "A new flight begins with status of SCHEDULED."

        Claim: POST /flights returns the flight with status=SCHEDULED.
        """
        insurer = create_insurer()
        resp = api.create_flight(
            insurer["id"],
            create_flight_payload(
                scheduled_departure_epoch_ms=10_000_000,
                scheduled_arrival_epoch_ms=15_000_000,
            ),
            TEST_USERS["claims_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_flight(data)
        assert data["status"] == FlightStatus.SCHEDULED.value


# ---------------------------------------------------------------------------
# Multi-source quorum (PRD §2.7)
# ---------------------------------------------------------------------------

class TestQuorum:
    def test_single_source_event_does_not_finalize(self, api):
        """PRD §2.7: "A quorum exists for a particular reported status when
        at least two distinct sources report it, and at least one of those
        distinct sources is AIRLINE or AVIATION_AUTHORITY."

        Claim: with only one ingested event, the flight remains SCHEDULED
        (no quorum).
        """
        insurer = create_insurer()
        flight = create_flight(insurer["id"])
        ingest_event(
            insurer["id"], flight["id"],
            source="AIRLINE",
            reported_status="DELAYED",
            reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
            reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
            reported_cause="AIRLINE",
        )
        f = get_flight(insurer["id"], flight["id"])
        assert f["status"] in (FlightStatus.SCHEDULED.value, FlightStatus.ACTIVE.value), \
            f"single-source event must not finalize flight; got {f['status']}"

    def test_two_distinct_sources_with_airline_drives_landed(self, api):
        """PRD §2.7: "A quorum exists for a particular reported status when
        at least two distinct sources report it, and at least one of those
        distinct sources is AIRLINE or AVIATION_AUTHORITY."

        Claim: AIRLINE + AVIATION_AUTHORITY both reporting DELAYED arrives
        at LANDED.
        """
        insurer = create_insurer()
        flight = create_flight(
            insurer["id"],
            scheduled_departure_epoch_ms=10_000_000,
            scheduled_arrival_epoch_ms=15_000_000,
        )
        # Ingest both quorum-bearing events at the same simulated clock time.
        ingest_event(
            insurer["id"], flight["id"],
            source="AIRLINE",
            reported_status="DELAYED",
            reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
            reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
            reported_cause="AIRLINE",
        )
        ingest_event(
            insurer["id"], flight["id"],
            source="AVIATION_AUTHORITY",
            reported_status="DELAYED",
            reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
            reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
            reported_cause="AIRLINE",
        )
        f = get_flight(insurer["id"], flight["id"])
        assert f["status"] == FlightStatus.LANDED.value

    def test_cancellation_quorum_drives_cancelled(self, api):
        """PRD §3.2: "a CANCELLED event drives it into CANCELLED (with both
        actual_departure_epoch_ms and actual_arrival_epoch_ms set to null,
        treated as an infinite delay sentinel)".

        Claim: 2 quorum CANCELLED events → flight.status=CANCELLED with null
        actual times.
        """
        insurer = create_insurer()
        flight = create_flight(insurer["id"])
        finalize_flight_cancelled(insurer["id"], flight["id"], cause="AIRLINE")
        f = get_flight(insurer["id"], flight["id"])
        assert f["status"] == FlightStatus.CANCELLED.value
        assert f.get("actual_departure_epoch_ms") in (None,)
        assert f.get("actual_arrival_epoch_ms") in (None,)


# ---------------------------------------------------------------------------
# Idempotency on event ingest (PRD §2.7)
# ---------------------------------------------------------------------------

class TestEventIdempotency:
    def test_duplicate_source_event_id_rejected(self, api):
        """PRD §2.7: "The triple (insurer_id, source, source_event_id) is
        unique; a duplicate event is rejected with ERR_DUPLICATE_EVENT (HTTP
        409)."

        Claim: re-posting the same (source, source_event_id) is rejected.
        """
        insurer = create_insurer()
        flight = create_flight(insurer["id"])
        evt_id = unique_source_event_id()
        # First event succeeds.
        first = api.ingest_flight_event(
            insurer["id"], flight["id"],
            flight_event_payload(
                source="AIRLINE",
                reported_status="DELAYED",
                source_event_id=evt_id,
                reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
                reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
            ),
            TEST_USERS["claims_admin_headers"],
        )
        validate_success(first, expected_status=201)
        # Same triple repeated — duplicate.
        dup = api.ingest_flight_event(
            insurer["id"], flight["id"],
            flight_event_payload(
                source="AIRLINE",
                reported_status="DELAYED",
                source_event_id=evt_id,
                reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
                reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
            ),
            TEST_USERS["claims_admin_headers"],
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_EVENT.value)


# ---------------------------------------------------------------------------
# Flight archive (PRD §3.2)
# ---------------------------------------------------------------------------

class TestFlightArchive:
    def test_archive_finalised_flight_succeeds(self, api):
        """PRD §3.2: "A finalised flight may be archived by a ClaimsAdmin
        ... Archive is permitted only if no claim referencing the flight is
        in PENDING_MATCH, MATCHED, UNDER_REVIEW, or APPROVED review status.
        On success, archived_at_epoch_ms is stamped from
        Insurer.now_epoch_ms and the flight transitions to ARCHIVED."

        Claim: a LANDED flight with no in-flight claims archives to ARCHIVED.
        """
        insurer = create_insurer()
        flight = setup_flight_with_delay(insurer["id"])
        resp = api.archive_flight(
            insurer["id"], flight["id"], TEST_USERS["claims_admin_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == FlightStatus.ARCHIVED.value
        assert data.get("archived_at_epoch_ms") is not None

    def test_archive_blocked_by_in_flight_claim(self, api):
        """PRD §3.2: "Archive is permitted only if no claim referencing the
        flight is in PENDING_MATCH, MATCHED, UNDER_REVIEW, or APPROVED
        review status."

        Claim: with a MATCHED claim referencing the flight, archive returns
        ERR_INVALID_STATE.
        """
        from test_helpers import setup_basic_claim_in_matched
        insurer, policy, flight, ticket, claim = setup_basic_claim_in_matched()
        resp = api.archive_flight(
            insurer["id"], flight["id"], TEST_USERS["claims_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
