"""Session state-machine transitions: open-enrollment, sweep-driven
ENROLLMENT_OPEN → ENROLLMENT_CLOSED → IN_PROGRESS, complete, cancel
(PRD §3.3, §3.5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    cancel_session_payload,
    create_session,
    drive_session_to_in_progress,
    iso_utc,
    run_sweep,
    setup_open_session,
    setup_session_environment,
    validate_error,
    validate_success,
)


SESSION_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
ENROLL_DEADLINE = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


# ===========================================================================
# SCHEDULED -> ENROLLMENT_OPEN (PRD §3.3)
# ===========================================================================
class TestOpenEnrollment:

    def test_open_enrollment_from_scheduled(self, api, training_admin_headers):
        """PRD §3.3: "A TrainingAdmin opens enrollment with the
        open-enrollment action, transitioning the session from
        SCHEDULED to ENROLLMENT_OPEN."

        Claim: SCHEDULED -> ENROLLMENT_OPEN on POST
        /sessions/{id}/open-enrollment.
        """
        env = setup_session_environment(tags=["engineering"])
        session = create_session(
            env["course"], env["instructor"],
            mode="ONSITE", classroom=env["classroom"],
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # Clock must be before deadline for the transition's
        # precondition (PRD §3.3).
        advance_clock_to(ENROLL_DEADLINE - timedelta(days=1))
        resp = api.open_session_enrollment(session["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ENROLLMENT_OPEN"


# ===========================================================================
# Sweep-driven transitions (PRD §3.3 + §2.10)
# ===========================================================================
class TestSweepDrivenStateAdvancement:

    def test_sweep_closes_enrollment_after_deadline(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "When the current time reaches or passes
        enrollment_deadline, an ENROLLMENT_OPEN session moves to
        ENROLLMENT_CLOSED."

        Claim: sweep at clock >= enrollment_deadline transitions
        ENROLLMENT_OPEN to ENROLLMENT_CLOSED.
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # Advance past the deadline, then sweep.
        advance_clock_to(ENROLL_DEADLINE + timedelta(minutes=1))
        run_sweep()
        resp = api.get_session(env["session"]["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] in ("ENROLLMENT_CLOSED", "IN_PROGRESS"), (
            f"Expected ENROLLMENT_CLOSED or IN_PROGRESS after sweep past "
            f"enrollment_deadline; got {data['status']}"
        )

    def test_sweep_starts_session_at_start_at(self, api, training_admin_headers):
        """PRD §3.3: "When the current time reaches or passes start_at,
        an ENROLLMENT_CLOSED session moves to IN_PROGRESS, at which
        point the check-in endpoints become active for the duration of
        the session."

        Claim: clock >= start_at -> IN_PROGRESS after sweep.
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        advance_clock_to(SESSION_START + timedelta(minutes=1))
        run_sweep()
        resp = api.get_session(env["session"]["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_PROGRESS", (
            f"Expected IN_PROGRESS after sweep past start_at; got {data['status']}"
        )


# ===========================================================================
# Complete (PRD §3.5)
# ===========================================================================
class TestSessionComplete:

    def test_complete_requires_clock_past_end_at(
        self, api, training_admin_headers,
    ):
        """PRD §3.5: "transitions the session from IN_PROGRESS to
        COMPLETED and requires that the current clock is at or past
        end_at."

        Claim: complete called BEFORE end_at -> ERR_INVALID_STATE
        (state machine precondition failure).
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # Drive into IN_PROGRESS but stay BEFORE end_at.
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        # Clock now > start_at but < end_at.
        resp = api.complete_session(env["session"]["id"], training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_complete_advances_in_progress_to_completed(
        self, api, training_admin_headers,
    ):
        """PRD §3.5: "transitions the session from IN_PROGRESS to
        COMPLETED."

        Claim: complete at clock >= end_at -> COMPLETED.
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        advance_clock_to(SESSION_END + timedelta(minutes=1))
        run_sweep()
        resp = api.complete_session(env["session"]["id"], training_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"


# ===========================================================================
# Cancel (PRD §3.3) — cascades to enrollments tested in test_06.
# ===========================================================================
class TestSessionCancel:

    def test_cancel_scheduled_marks_status_cancelled(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "A session may also be cancelled by a
        TrainingAdmin from any non-terminal state."

        Claim: cancel on SCHEDULED -> CANCELLED.
        """
        env = setup_session_environment(tags=["engineering"])
        session = create_session(
            env["course"], env["instructor"],
            mode="ONSITE", classroom=env["classroom"],
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        resp = api.cancel_session(
            session["id"],
            cancel_session_payload(reason="Logistics"),
            training_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"

    def test_cancel_within_48h_window_charges_fee(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "if the moment of cancellation is at or past
        start_at minus 48 hours, the session's cancellation_fee_charged
        is set to true."

        Claim: cancel with clock >= start_at - 48h ->
        cancellation_fee_charged=true.
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # 24 hours before start -> inside 48h window.
        advance_clock_to(SESSION_START - timedelta(hours=24))
        resp = api.cancel_session(
            env["session"]["id"],
            cancel_session_payload(reason="Within window"),
            training_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"
        assert data["cancellation_fee_charged"] is True

    def test_cancel_outside_48h_window_no_fee(
        self, api, training_admin_headers,
    ):
        """PRD §3.3: "if the moment of cancellation is at or past
        start_at minus 48 hours, the session's
        cancellation_fee_charged is set to true."

        Claim (contrapositive): cancel with clock < start_at - 48h ->
        cancellation_fee_charged=false.
        """
        env = setup_open_session(
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # 72 hours before start -> outside the 48-hour window.
        advance_clock_to(SESSION_START - timedelta(hours=72))
        resp = api.cancel_session(
            env["session"]["id"],
            cancel_session_payload(reason="Outside window"),
            training_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"
        assert data["cancellation_fee_charged"] is False
