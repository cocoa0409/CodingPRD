"""Concurrency / race semantics.

PRD §2.10. Each race generates two operations that may execute in
parallel; the PRD pins the loser's error_id, so we assert it
explicitly.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    iso_anchor_offset,
    make_therapist_headers,
    run_race,
    setup_checked_in_appointment,
    setup_completed_session_and_claim,
    setup_in_progress_session,
    setup_posted_claim_for_void_window,
    setup_scheduled_appointment,
    validate_error,
)


class TestRaceCheckIn:

    def test_two_simultaneous_checkins_serialize_on_status(self, api):
        """PRD §2.10: "Two simultaneous check-ins on the same
        appointment serialise on Appointment.status: exactly one
        transitions SCHEDULED → CHECKED_IN, and the loser observes the
        new CHECKED_IN state and is rejected with ERR_APPT_NOT_OPEN."

        Claim: when two check-ins race for the same appointment,
        exactly one succeeds and the loser is rejected with
        ERR_APPT_NOT_OPEN.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        # Move into the check-in window.
        advance_clock_to(iso_anchor_offset(minutes=119))
        appt_id = bundle["appointment"]["id"]
        therapist_id = bundle["therapist"]["id"]
        results = run_race(
            lambda: api.checkin_appointment(
                appt_id, make_therapist_headers(therapist_id),
            ),
            lambda: api.checkin_appointment(
                appt_id, make_therapist_headers(therapist_id),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_APPT_NOT_OPEN")


class TestRaceSessionComplete:

    def test_two_simultaneous_completes_serialize_on_session(self, api):
        """PRD §2.10: "Two simultaneous complete requests on the same
        session — or a complete racing a void on the same session —
        serialise on Session.status; the loser is rejected with
        ERR_SESSION_NOT_OPEN."

        Claim: two simultaneous /sessions/{id}/complete calls on the
        same session serialize: one succeeds, the other gets
        ERR_SESSION_NOT_OPEN.
        """
        bundle = setup_in_progress_session()
        session_id = bundle["session"]["id"]
        therapist_id = bundle["therapist"]["id"]
        results = run_race(
            lambda: api.complete_session(
                session_id, make_therapist_headers(therapist_id),
            ),
            lambda: api.complete_session(
                session_id, make_therapist_headers(therapist_id),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_SESSION_NOT_OPEN")

    def test_complete_vs_void_serialize_on_session(self, api):
        """PRD §2.10: "Two simultaneous complete requests on the same
        session — or a complete racing a void on the same session —
        serialise on Session.status; the loser is rejected with
        ERR_SESSION_NOT_OPEN."

        Claim: a /complete racing a /void on the same session — exactly
        one transition wins; the loser gets ERR_SESSION_NOT_OPEN.
        """
        bundle = setup_in_progress_session()
        session_id = bundle["session"]["id"]
        therapist_id = bundle["therapist"]["id"]
        results = run_race(
            lambda: api.complete_session(
                session_id, make_therapist_headers(therapist_id),
            ),
            lambda: api.void_session(
                session_id, TEST_USERS["practice_admin_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_SESSION_NOT_OPEN")


class TestRaceClaimVoid:

    def test_two_simultaneous_void_requests_serialize_on_claim(self, api):
        """PRD §2.10: "Two simultaneous void requests on the same
        claim serialise on BillingClaim.status; the loser is rejected
        with ERR_CLAIM_NOT_POSTED."

        Claim: two simultaneous /claims/{id}/void requests for the
        same claim serialize: one succeeds, the other gets
        ERR_CLAIM_NOT_POSTED.
        """
        bundle = setup_posted_claim_for_void_window()
        claim_id = bundle["claim"]["id"]
        results = run_race(
            lambda: api.void_claim(
                claim_id, TEST_USERS["practice_admin_headers"],
            ),
            lambda: api.void_claim(
                claim_id, TEST_USERS["practice_admin_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_CLAIM_NOT_POSTED")
