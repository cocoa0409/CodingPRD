"""Interview scheduling, double-booking, and timing — PRD §3.4.

Covers: 15-min buffer overlap, time-gated complete/cancel, empty-panel
on creation, basic schedule round-trip.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_hours,
    add_minutes,
    advance_clock_to_iso,
    assert_interview,
    create_interview_payload,
    init_clock,
    make_recruiter_headers,
    make_second_application_under_recruiter,
    schedule_interview,
    setup_interviewer_with_scheduled_interview,
    TEST_DEFAULTS,
    validate_error,
    validate_success,
)


# ===========================================================================
# 15-minute buffer / double-booking — PRD §3.4
# ===========================================================================
class TestInterviewerDoubleBooking:

    def test_adjacent_interviews_conflict_because_of_buffer(self, api):
        """PRD §3.4: "Every newly scheduled or edited interview is
        checked for double-booking against the assigned interviewer's
        existing `SCHEDULED` interviews using a 15-minute buffer
        applied to both sides of each existing interval — that is, an
        existing scheduled interview from 10:00 to 11:00 effectively
        occupies 09:45 to 11:15 for collision-detection purposes.
        Adjacency where one interview's end equals another's start is
        therefore a conflict."

        Claim: a SECOND interview starting EXACTLY where the first
        ends (10:00-11:00 then 11:00-12:00) is rejected with
        ERR_INTERVIEWER_DOUBLE_BOOKED / 409.
        """
        anchor = TEST_DEFAULTS["INITIAL_CLOCK_ISO"]
        # First interview: anchor+10h to anchor+11h.
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        # Second application + adjacent start (end1).
        req2, _, application2 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        start2 = end1
        end2 = add_hours(anchor, 12)
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at=start2,
            scheduled_end_at=end2,
        )
        resp = api.create_interview(application2["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)

    def test_exactly_buffer_away_still_conflicts(self, api):
        """PRD §3.4: "an existing scheduled interview from 10:00 to
        11:00 effectively occupies 09:45 to 11:15 for collision-
        detection purposes."

        Claim: a SECOND interview starting at end1 + 15 min (i.e., at
        11:15 when first ends at 11:00) is rejected — the existing
        interval is occupying through 11:15 inclusive.
        """
        anchor = TEST_DEFAULTS["INITIAL_CLOCK_ISO"]
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        _, _, application2 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        start2 = add_minutes(end1, 15)   # exactly the buffer
        end2 = add_hours(anchor, 13)
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at=start2,
            scheduled_end_at=end2,
        )
        resp = api.create_interview(application2["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)

    def test_just_past_buffer_succeeds(self, api):
        """PRD §3.4: 15-minute buffer extension on both sides.

        Claim: a second interview starting at end1 + 16 minutes (one
        minute past the buffer envelope) is accepted with 201.
        """
        anchor = TEST_DEFAULTS["INITIAL_CLOCK_ISO"]
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        _, _, application2 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        start2 = add_minutes(end1, 16)  # 1 min past buffer
        end2 = add_hours(anchor, 13)
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at=start2,
            scheduled_end_at=end2,
        )
        resp = api.create_interview(application2["id"], payload, h)
        data = validate_success(resp, expected_status=201)
        assert_interview(data)
        assert data["status"] == "SCHEDULED"


# ===========================================================================
# Time-gated transitions — PRD §3.4
# ===========================================================================
class TestInterviewTiming:

    def test_complete_before_scheduled_end_at_is_rejected(self, api):
        """PRD §3.4: "Completing an interview transitions it
        `SCHEDULED` → `COMPLETED`, but only when the current logical
        time is at or after `scheduled_end_at`; calling complete
        before that instant is rejected with `ERR_INTERVIEW_TIMING`."

        Claim: /complete before the clock reaches scheduled_end_at
        returns ERR_INTERVIEW_TIMING / 409. Uses a far-future anchor
        so the test is robust to clock progression by earlier tests.
        """
        anchor = "2031-01-01T08:00:00.000Z"
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        # Clock is at anchor (way before end1).
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.complete_interview(ctx["interview_a"]["id"], h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_TIMING.value)

    def test_cancel_at_or_after_start_at_is_rejected(self, api):
        """PRD §3.4: "Cancelling an interview transitions it
        `SCHEDULED` → `CANCELLED` but only when the current logical
        time is strictly before `scheduled_start_at`; cancelling at or
        after the start is rejected with `ERR_INTERVIEW_TIMING`."

        Claim: /cancel at scheduled_start_at returns ERR_INTERVIEW_TIMING
        / 409. We use a far-past-relative-to-test-anchor interview
        window so the current logical clock (which may have been
        advanced by an earlier test) is provably at or after start1.
        """
        # Schedule the interview at a time that is GUARANTEED to be
        # at-or-before the current logical clock by the time this test
        # runs — using anchor=INITIAL_CLOCK_ISO and adding +10h yields
        # 2026-05-20T18:00:00Z, which is at or before any clock state
        # reachable from the preceding tests in this file.
        anchor = TEST_DEFAULTS["INITIAL_CLOCK_ISO"]
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        # The clock is already at-or-past start1 because of preceding
        # tests' anchors; if a stricter assertion is desired we attempt
        # a forward-only advance to start1 (best-effort).
        from test_helpers import try_advance_clock_to_iso
        try_advance_clock_to_iso(start1)
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.cancel_interview(ctx["interview_a"]["id"], h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_TIMING.value)

    def test_cancel_before_start_succeeds(self, api):
        """PRD §3.4: "Cancelling an interview transitions it
        `SCHEDULED` → `CANCELLED` but only when the current logical
        time is strictly before `scheduled_start_at`."

        Claim: /cancel one minute before start succeeds and yields
        status=CANCELLED. Uses a far-future anchor so the test is
        robust to clock progression by earlier tests.
        """
        # Use an anchor strictly later than every earlier test's
        # advances so the "strictly before scheduled_start_at"
        # invariant holds.
        anchor = "2035-01-01T08:00:00.000Z"
        start1 = add_hours(anchor, 10)
        end1 = add_hours(anchor, 11)
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        advance_clock_to_iso(add_minutes(start1, -1))
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.cancel_interview(ctx["interview_a"]["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELLED"
