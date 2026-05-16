"""TestEvent lifecycle and deadline extension.

Covers PRD §3.1 (state machine across REGISTRATION_OPEN ->
REGISTRATION_CLOSED -> SCORES_PENDING -> COMPLETED), and the once-only
Registrar deadline-extension override.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    assert_test_event,
    assert_version_bumped,
    create_event_with_capacity,
    create_test_event,
    extend_deadline_payload,
    fmt_iso,
    parse_iso,
    reset_clock_to,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation
# ===========================================================================
class TestTestEventCreation:
    def test_create_event_starts_in_registration_open(self, api):
        """PRD §3.1: "The event starts life in `REGISTRATION_OPEN`."

        Claim: a freshly created TestEvent has status REGISTRATION_OPEN.
        """
        event = create_test_event()
        assert_test_event(event)
        assert event["status"] == "REGISTRATION_OPEN", (
            "PRD §3.1: new TestEvent starts in REGISTRATION_OPEN"
        )
        assert event["version"] == 1

    @pytest.mark.parametrize("test_type", ["SAT", "ACT", "AP", "CLEP"])
    def test_create_event_accepts_all_four_test_types(self, api, test_type):
        """PRD §3.1: "the test program (`test_type` is one of `SAT`,
        `ACT`, `AP`, or `CLEP`)".

        Claim: each of the four programs is accepted on creation.
        """
        # AP and CLEP require a subject per PRD §3.1.
        subject = None
        if test_type == "AP":
            subject = "AP_CALC_BC"
        elif test_type == "CLEP":
            subject = "CLEP_COLLEGE_ALGEBRA"
        event = create_test_event(test_type=test_type, subject=subject)
        assert event["test_type"] == test_type


# ===========================================================================
# Auto-close on clock crossing late_registration_deadline
# ===========================================================================
class TestRegistrationClose:
    def test_clock_crossing_late_deadline_closes_registration(self, api):
        """PRD §3.1: "When the logical clock crosses
        `late_registration_deadline`, the system advances the event
        from `REGISTRATION_OPEN` to `REGISTRATION_CLOSED`."

        Claim: after advancing clock past late_registration_deadline
        the event's status is REGISTRATION_CLOSED.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        # Advance past late_registration_deadline.
        advance_clock_to("2026-06-05T00:00:00.000Z")
        res = api.get_test_event(event["id"], TEST_USERS["registrar_headers"])
        refreshed = validate_success(res, 200)
        assert refreshed["status"] == "REGISTRATION_CLOSED", (
            "PRD §3.1: clock crossing late_registration_deadline closes registration"
        )


# ===========================================================================
# Registrar extend-deadline override
# ===========================================================================
class TestExtendDeadline:
    def test_extend_reopens_closed_event_once(self, api):
        """PRD §3.1: "A `Registrar` may, exactly once per event,
        override this closure by supplying a new late-registration
        deadline that lies in the future; this transitions the event
        back from `REGISTRATION_CLOSED` to `REGISTRATION_OPEN`,
        updates the `late_registration_deadline` on the row, and bumps
        the event's `version` by one."

        Claim: extend-deadline on a CLOSED event reopens it and bumps
        version by 1.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-15T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-01T00:00:00.000Z",
            score_release_date="2026-06-22T00:00:00.000Z",
        )
        advance_clock_to("2026-06-02T00:00:00.000Z")
        # Confirm closure.
        before = validate_success(
            api.get_test_event(event["id"], TEST_USERS["registrar_headers"]), 200,
        )
        assert before["status"] == "REGISTRATION_CLOSED"

        new_deadline = "2026-06-10T00:00:00.000Z"
        res = api.extend_deadline(
            event["id"],
            extend_deadline_payload(new_deadline),
            TEST_USERS["registrar_headers"],
        )
        after = validate_success(res, 200)
        assert after["status"] == "REGISTRATION_OPEN", (
            "PRD §3.1: extend-deadline reopens REGISTRATION_CLOSED -> REGISTRATION_OPEN"
        )
        assert after["late_registration_deadline"].startswith("2026-06-10")
        assert_version_bumped(before, after)

    def test_second_extension_rejected(self, api):
        """PRD §3.1: "A second extension on the same event is rejected
        with `ERR_DEADLINE_EXTENSION_EXHAUSTED`."

        Claim: calling extend-deadline twice on the same event yields
        ERR_DEADLINE_EXTENSION_EXHAUSTED on the second call.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-30T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-01T00:00:00.000Z",
            score_release_date="2026-07-07T00:00:00.000Z",
        )
        advance_clock_to("2026-06-02T00:00:00.000Z")

        # First extension succeeds.
        validate_success(
            api.extend_deadline(
                event["id"],
                extend_deadline_payload("2026-06-10T00:00:00.000Z"),
                TEST_USERS["registrar_headers"],
            ),
            200,
        )
        # Close again to make a second extension semantically meaningful.
        advance_clock_to("2026-06-11T00:00:00.000Z")
        res = api.extend_deadline(
            event["id"],
            extend_deadline_payload("2026-06-20T00:00:00.000Z"),
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DEADLINE_EXTENSION_EXHAUSTED.value)


# ===========================================================================
# SCORES_PENDING and COMPLETED transitions
# ===========================================================================
class TestScoresPendingAndCompleted:
    def test_clock_past_score_release_completes_event(self, api):
        """PRD §3.1: "when the clock crosses `score_release_date`, the
        event moves from `SCORES_PENDING` to `COMPLETED`".

        Claim: after running the sweep past test-session and then
        advancing past score_release_date, the event is COMPLETED.
        """
        from test_helpers import drive_event_to_completed
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event, _, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        # Close the event by crossing late_registration_deadline.
        advance_clock_to("2026-06-05T00:00:00.000Z")
        final = drive_event_to_completed(
            event["id"],
            "2026-06-08T09:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
        )
        assert final["status"] == "COMPLETED", (
            "PRD §3.1: clock past score_release_date completes the event"
        )
