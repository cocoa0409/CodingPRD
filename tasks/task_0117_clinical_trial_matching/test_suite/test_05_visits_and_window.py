"""Visits — scheduling, blood-draw window boundaries, mark-missed,
cancel.

PRD §3.6 (visit lifecycle), §2.9 (window semantics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_VISIT_CENTS,
    LATE_PENALTY_CENTS,
    ON_TIME_BONUS_CENTS,
    TEST_USERS,
    advance_clock_to,
    assert_visit,
    complete_visit_payload,
    create_visit_payload,
    iso_anchor_offset,
    schedule_visit,
    setup_enrolled_participant,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 Visit creation — sequence_no uniqueness.
# ===========================================================================
class TestVisitCreation:
    """PRD §3.6 sequence_no rules."""

    def test_duplicate_sequence_no_rejected(self, api):
        """PRD §3.6: "Each visit creation carries a 1-indexed
        sequence_no between 1 and 50 that must be unique within the
        participant (any duplicate is ERR_DUPLICATE_VISIT_SEQUENCE)".

        Claim: a second visit with the same sequence_no on the same
        participant returns ERR_DUPLICATE_VISIT_SEQUENCE.
        """
        trial, p, _arms = setup_enrolled_participant()
        schedule_visit(
            p["id"], sequence_no=3,
            target_date=iso_anchor_offset(days=10),
        )
        res = api.create_visit(
            p["id"],
            create_visit_payload(
                sequence_no=3,
                target_date=iso_anchor_offset(days=25),
            ),
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_DUPLICATE_VISIT_SEQUENCE")

    def test_visit_created_in_scheduled(self, api):
        """PRD §3.6: "The visit begins in SCHEDULED, with actual_draw_at
        null and compensation_cents at zero".

        Claim: a new visit is in SCHEDULED with actual_draw_at null
        and compensation_cents == 0.
        """
        trial, p, _arms = setup_enrolled_participant()
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        assert_visit(v)
        assert v["status"] == "SCHEDULED"
        assert v.get("actual_draw_at") is None
        assert v["compensation_cents"] == 0


# ===========================================================================
# §2.9 blood-draw window — INCLUSIVE boundary.
# ===========================================================================
class TestBloodDrawWindow:
    """PRD §2.9: "The boundary is inclusive on both sides: a draw on
    target_date + blood_draw_window_days is within the window; a draw
    on target_date + blood_draw_window_days + 1 is outside.\""""

    def test_draw_at_window_upper_boundary_succeeds(self, api):
        """PRD §2.9: "a draw on target_date + blood_draw_window_days is
        within the window".

        Claim: a draw exactly at target_date + 7 days on a trial with
        blood_draw_window_days=7 completes successfully.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        # d=7: actual_draw_at is anchor + 17 days at 12:00.
        advance_clock_to(iso_anchor_offset(days=17, hours=12))
        res = api.complete_visit(
            v["id"],
            {"actual_draw_at": iso_anchor_offset(days=17, hours=12)},
            TEST_USERS["study_coordinator_headers"],
        )
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"

    def test_draw_one_day_past_window_returns_outside_window(self, api):
        """PRD §2.9: "a draw on target_date + blood_draw_window_days + 1
        is outside."

        Claim: a draw at target_date + 8 days on a trial with
        blood_draw_window_days=7 fires ERR_DRAW_OUTSIDE_WINDOW.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        advance_clock_to(iso_anchor_offset(days=18, hours=12))
        res = api.complete_visit(
            v["id"],
            {"actual_draw_at": iso_anchor_offset(days=18, hours=12)},
            TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_DRAW_OUTSIDE_WINDOW")

    def test_on_time_draw_pays_base_plus_on_time_bonus(self, api):
        """PRD §3.8: "When d equals zero — the draw is exactly on
        target_date — the bonus is the on-time bonus of 1000 cents."

        Claim: an on-time draw produces compensation_cents = 5000 +
        1000 = 6000.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        advance_clock_to(iso_anchor_offset(days=10, hours=12))
        res = api.complete_visit(
            v["id"],
            {"actual_draw_at": iso_anchor_offset(days=10, hours=12)},
            TEST_USERS["study_coordinator_headers"],
        )
        completed = validate_success(res, 200)
        assert completed["compensation_cents"] == (
            BASE_VISIT_CENTS + ON_TIME_BONUS_CENTS
        )


# ===========================================================================
# §3.6 mark-missed — gated by window expiry.
# ===========================================================================
class TestMarkMissed:
    """PRD §3.6 mark-missed gate."""

    def test_mark_missed_before_window_passes_fires_window_not_yet_passed(
        self, api,
    ):
        """PRD §3.6: "A premature attempt is ERR_WINDOW_NOT_YET_PASSED."

        Claim: marking a visit MISSED while the clock is still within
        target_date + window fires ERR_WINDOW_NOT_YET_PASSED.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        # Clock at day 17 = target_date + window (still on the boundary,
        # not strictly past).
        advance_clock_to(iso_anchor_offset(days=17, hours=12))
        res = api.mark_visit_missed(
            v["id"], TEST_USERS["study_coordinator_headers"],
        )
        validate_error(res, "ERR_WINDOW_NOT_YET_PASSED")

    def test_mark_missed_after_window_succeeds(self, api):
        """PRD §3.6: "The coordinator may mark SCHEDULED → MISSED only
        when the current logical clock time is strictly later than
        target_date plus blood_draw_window_days — that is, the window
        must have fully passed."

        Claim: marking missed when the clock is strictly past
        target_date + window succeeds and moves the visit to MISSED.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        # day 18 is strictly past day 17 = target + 7.
        advance_clock_to(iso_anchor_offset(days=18, hours=12))
        res = api.mark_visit_missed(
            v["id"], TEST_USERS["study_coordinator_headers"],
        )
        m = validate_success(res, 200)
        assert m["status"] == "MISSED"


# ===========================================================================
# §3.6 delete-cancel.
# ===========================================================================
class TestDeleteVisit:
    """PRD §3.6: "A visit may also be cancelled outright while it is
    still SCHEDULED, either by a direct delete request from the
    coordinator or by cascade from a parent operation."

    PRD §4: "the visit delete-cancel which returns 204 No Content".
    """

    def test_delete_cancels_scheduled_visit_returns_204(self, api):
        """PRD §4: "the visit delete-cancel which returns 204 No
        Content".

        Claim: DELETE /visits/{id} on a SCHEDULED visit returns 204.
        """
        trial, p, _arms = setup_enrolled_participant(
            blood_draw_window_days=7,
        )
        v = schedule_visit(
            p["id"], sequence_no=1,
            target_date=iso_anchor_offset(days=10),
        )
        res = api.delete_visit(
            v["id"], TEST_USERS["study_coordinator_headers"],
        )
        assert res.status_code == 204, (
            f"DELETE /visits/{{id}} must return 204; "
            f"got {res.status_code}"
        )
