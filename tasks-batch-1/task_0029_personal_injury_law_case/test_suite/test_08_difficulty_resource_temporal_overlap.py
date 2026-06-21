"""Difficulty Rule 8 — resource_temporal_overlap.

Two collision shapes on different resource entities:

  • CourtEvent — 24-hour buffered interval, closed on both ends (PRD §3.8)
  • MedicalRecordsRequest — unbuffered identity overlap on (case_id, provider_id)
    when an existing request is in REQUESTED or RECEIVED (PRD §3.2)
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    create_court_event,
    ApiErrorId,
    api_client,
    create_court_event_payload,
    create_records_request_payload,
    make_attorney_headers,
    make_paralegal_headers,
    setup_active_case,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: court_event_hearing_within_24h_buffer_conflict
# =============================================================================


class TestCourtEventHearingWithin24hBufferConflict:
    """A new HEARING/TRIAL/MEDIATION on a case must not overlap an existing
    SCHEDULED event once a 24-hour buffer is applied. Two HEARINGs scheduled
    12 hours apart collide even though their raw intervals are disjoint."""

    def test_hearing_within_24h_of_existing_hearing_returns_conflict(self, api):
        """PRD §3.8: "Conflict avoidance is enforced for `HEARING`, `TRIAL`,
        and `MEDIATION` events: a new event of one of those types on a given
        `case_id` must not overlap any existing `SCHEDULED` event on the same
        `case_id` once a 24-hour buffer is applied to both ends of the new
        event — that is, the interval running from 24 hours before the new
        event's `scheduled_at` to 24 hours after the new event's
        `scheduled_at` plus its `duration_minutes` must not intersect the
        existing event's interval running from its `scheduled_at` to its
        `scheduled_at` plus its `duration_minutes`. Both endpoints are closed
        on both sides, so an exact-touch collision counts. A conflict is
        rejected with `ERR_COURT_EVENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/court_event_hearing_within_24h_buffer_conflict
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case = setup_active_case()
        create_court_event(case["id"], "HEARING", "2026-08-01T14:00:00Z",
                            duration_minutes=60)
        # 12 hours later — well inside the 24h buffer.
        headers = make_attorney_headers("attorney-8a")
        res = api_client.create_court_event(
            create_court_event_payload(case["id"], "HEARING",
                                        "2026-08-02T02:00:00Z",
                                        duration_minutes=60),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_COURT_EVENT_CONFLICT.value)

    def test_hearing_just_outside_24h_buffer_succeeds(self, api):
        """PRD §3.8: "Conflict avoidance is enforced for `HEARING`, `TRIAL`,
        and `MEDIATION` events: a new event of one of those types on a given
        `case_id` must not overlap any existing `SCHEDULED` event on the same
        `case_id` once a 24-hour buffer is applied to both ends of the new
        event — that is, the interval running from 24 hours before the new
        event's `scheduled_at` to 24 hours after the new event's
        `scheduled_at` plus its `duration_minutes` must not intersect the
        existing event's interval running from its `scheduled_at` to its
        `scheduled_at` plus its `duration_minutes`. Both endpoints are closed
        on both sides, so an exact-touch collision counts. A conflict is
        rejected with `ERR_COURT_EVENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/court_event_hearing_within_24h_buffer_conflict
        """
        # First event 60-minute HEARING ending at 2026-08-01T15:00:00Z.
        # New event at 2026-08-02T15:01:00Z (24h + 1 min after the END of the
        # first event) — the new event's −24h buffer point sits at
        # 2026-08-01T15:01:00Z, one minute after the existing event ends, so
        # intervals do not intersect.
        set_clock("2026-01-01T00:00:00Z")
        client, case = setup_active_case()
        create_court_event(case["id"], "HEARING", "2026-08-01T14:00:00Z",
                            duration_minutes=60)
        ev2 = create_court_event(case["id"], "HEARING",
                                  "2026-08-02T15:01:00Z",
                                  duration_minutes=60)
        assert ev2["status"] == "SCHEDULED"


# =============================================================================
# Instance: duplicate_active_records_request_conflict
# =============================================================================


class TestDuplicateActiveRecordsRequestConflict:
    """A second MedicalRecordsRequest with the same (case_id, provider_id) is
    rejected when an existing one is in REQUESTED or RECEIVED. The collision
    is pure identity overlap — no time component or buffer."""

    def test_duplicate_request_while_first_is_requested_returns_duplicate(self, api):
        """PRD §3.2: "The system rejects a duplicate active request — defined
        as a request for the same `case_id` and `provider_id` whose current
        status is `REQUESTED` or `RECEIVED` — with
        `ERR_DUPLICATE_RECORDS_REQUEST`; the system does not impose any time
        buffer on this collision rule, so any two simultaneously-active
        requests for the same pair conflict regardless of when they were
        filed."

        Design: Difficulty/resource_temporal_overlap/duplicate_active_records_request_conflict
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case = setup_active_case()
        provider = register_provider()
        create_records_request(case["id"], provider["id"])
        # A second request on the same (case_id, provider_id) while the first
        # is still REQUESTED.
        headers = make_paralegal_headers("paralegal-8b")
        res = api_client.create_records_request(
            create_records_request_payload(case["id"], provider["id"]),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORDS_REQUEST.value)

    def test_duplicate_request_while_first_is_received_returns_duplicate(self, api):
        """PRD §3.2: "The system rejects a duplicate active request — defined
        as a request for the same `case_id` and `provider_id` whose current
        status is `REQUESTED` or `RECEIVED` — with
        `ERR_DUPLICATE_RECORDS_REQUEST`; the system does not impose any time
        buffer on this collision rule, so any two simultaneously-active
        requests for the same pair conflict regardless of when they were
        filed."

        Design: Difficulty/resource_temporal_overlap/duplicate_active_records_request_conflict
        """
        from test_helpers import TEST_USERS
        set_clock("2026-01-01T00:00:00Z")
        client, case = setup_active_case()
        provider = register_provider()
        first = create_records_request(case["id"], provider["id"])
        # Walk first to RECEIVED — still an "active" state per PRD §3.2.
        api_client.receive_records_request(first["id"], TEST_USERS["paralegal_headers"])
        headers = make_paralegal_headers("paralegal-8c")
        res = api_client.create_records_request(
            create_records_request_payload(case["id"], provider["id"]),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORDS_REQUEST.value)
