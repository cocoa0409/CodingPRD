"""Service sessions — PRD §3.6.

Covers: scheduled_minutes formula, closed-interval adjacency overlap,
deliver gates, cancel.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    assert_service_session,
    cancel_session,
    create_session,
    create_session_payload,
    deliver_session,
    deliver_session_payload,
    get_service,
    setup_active_iep_with_active_service,
    validate_error,
    validate_success,
)


class TestSessionScheduledMinutesFormula:

    def test_scheduled_minutes_floor_of_seconds_over_60(self, api):
        """PRD §3.6: "The server computes scheduled_minutes as the
        floor of the difference between scheduled_end and
        scheduled_start measured in seconds, divided by 60 — this
        formula is pinned."

        Claim: a 25-minute session has scheduled_minutes==25; a
        25-minute-30-second session also rounds down to 25.
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2025-03-01T09:00:00.000Z",
            scheduled_end="2025-03-01T09:25:00.000Z",
        )
        assert s["scheduled_minutes"] == 25

        # 25 minutes 30 seconds → floor(1530 / 60) = 25.
        s2 = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2025-03-08T09:00:00.000Z",
            scheduled_end="2025-03-08T09:25:30.000Z",
        )
        assert s2["scheduled_minutes"] == 25

    def test_scheduled_end_not_after_start_rejected(self, api):
        """PRD §3.6: "with scheduled_end strictly greater than
        scheduled_start (else ERR_INVALID_REQUEST)".

        Claim: scheduled_end == scheduled_start → ERR_INVALID_REQUEST.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        res = api.create_session(
            district["id"], student["id"], iep["id"], service["id"],
            create_session_payload(
                scheduled_start="2025-03-01T09:00:00.000Z",
                scheduled_end="2025-03-01T09:00:00.000Z",
            ),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_INVALID_REQUEST")


class TestSessionOverlap:

    def test_closed_interval_adjacency_overlap_rejected(self, api):
        """PRD §3.6: "Two sessions on the same related_service_id may
        not overlap in time; overlap is checked on closed intervals
        so that adjacency (one session's scheduled_end equal to
        another's scheduled_start) counts as a violation, and a
        conflicting create is rejected with
        ERR_SERVICE_SESSION_OVERLAP."

        Claim: two sessions where session_A.scheduled_end ==
        session_B.scheduled_start → second is rejected with
        ERR_SERVICE_SESSION_OVERLAP.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        # First session.
        create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2025-03-01T09:00:00.000Z",
            scheduled_end="2025-03-01T10:00:00.000Z",
        )
        # Second session: starts at exact end of first.
        res = api.create_session(
            district["id"], student["id"], iep["id"], service["id"],
            create_session_payload(
                scheduled_start="2025-03-01T10:00:00.000Z",
                scheduled_end="2025-03-01T11:00:00.000Z",
            ),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_SESSION_OVERLAP")

    def test_partial_overlap_rejected(self, api):
        """PRD §3.6: "Two sessions on the same related_service_id may
        not overlap in time".

        Claim: any partial overlap is rejected.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2025-03-01T09:00:00.000Z",
            scheduled_end="2025-03-01T10:00:00.000Z",
        )
        res = api.create_session(
            district["id"], student["id"], iep["id"], service["id"],
            create_session_payload(
                scheduled_start="2025-03-01T09:30:00.000Z",
                scheduled_end="2025-03-01T10:30:00.000Z",
            ),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SERVICE_SESSION_OVERLAP")


class TestSessionDeliver:

    def test_deliver_before_scheduled_start_rejected(self, api):
        """PRD §3.6: "the district's current_date be at or after
        scheduled_start (else ERR_SESSION_NOT_DUE_YET)".

        Claim: deliver on a session whose scheduled_start is in the
        future → ERR_SESSION_NOT_DUE_YET.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        # Schedule far in the future relative to the initial clock
        # 2025-01-01.
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2026-01-01T09:00:00.000Z",
            scheduled_end="2026-01-01T10:00:00.000Z",
        )
        res = api.deliver_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"],
            deliver_session_payload(actual_minutes=60),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SESSION_NOT_DUE_YET")

    def test_deliver_actual_minutes_must_not_exceed_scheduled(
        self, api,
    ):
        """PRD §3.6: "a non-negative integer at most equal to the
        session's scheduled_minutes".

        Claim: actual_minutes > scheduled_minutes → ERR_INVALID_REQUEST.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        # 60-min session scheduled in the past so the due-yet gate
        # passes.
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2024-12-15T09:00:00.000Z",
            scheduled_end="2024-12-15T10:00:00.000Z",
        )
        res = api.deliver_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"],
            deliver_session_payload(actual_minutes=61),
            TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_deliver_succeeds_updates_total_delivered_minutes(
        self, api,
    ):
        """PRD §3.6: "On success the session moves to DELIVERED, the
        parent service's total_delivered_minutes increases by
        actual_minutes".

        Claim: post-deliver, service.total_delivered_minutes ==
        actual_minutes.
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2024-12-15T09:00:00.000Z",
            scheduled_end="2024-12-15T10:00:00.000Z",
        )
        deliver_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"], actual_minutes=45,
        )
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["total_delivered_minutes"] == 45


class TestSessionCancel:

    def test_cancel_scheduled_session_succeeds(self, api):
        """PRD §3.6: "A SCHEDULED session may instead be cancelled.
        Cancel requires the session to be in SCHEDULED (else
        ERR_SESSION_NOT_SCHEDULED); on success the session moves to
        CANCELLED and the parent service's total_cancelled_minutes
        increases by the session's scheduled_minutes."

        Claim: cancel moves session to CANCELLED and updates the
        service's total_cancelled_minutes.
        """
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2025-03-01T09:00:00.000Z",
            scheduled_end="2025-03-01T09:30:00.000Z",
        )
        cancel_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"],
        )
        svc_now = get_service(
            district["id"], student["id"], iep["id"], service["id"],
        )
        assert svc_now["total_cancelled_minutes"] == 30

    def test_cancel_non_scheduled_session_rejected(self, api):
        """PRD §3.6: "Cancel requires the session to be in SCHEDULED
        (else ERR_SESSION_NOT_SCHEDULED)".

        Claim: cancelling an already-DELIVERED session →
        ERR_SESSION_NOT_SCHEDULED.
        """
        from test_helpers import TEST_USERS
        district, student, iep, service, _consent = (
            setup_active_iep_with_active_service()
        )
        s = create_session(
            district["id"], student["id"], iep["id"], service["id"],
            scheduled_start="2024-12-15T09:00:00.000Z",
            scheduled_end="2024-12-15T09:30:00.000Z",
        )
        deliver_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"], actual_minutes=30,
        )
        res = api.cancel_session(
            district["id"], student["id"], iep["id"], service["id"],
            s["id"], TEST_USERS["provider_headers"],
        )
        validate_error(res, "ERR_SESSION_NOT_SCHEDULED")
