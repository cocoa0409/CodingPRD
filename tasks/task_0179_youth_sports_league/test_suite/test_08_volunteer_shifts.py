"""Volunteer shift lifecycle: schedule, check-in, approve.

PRD §2.9 (volunteer crediting principle) and §3.7 (shift lifecycle)
drive this file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    VOLUNTEER_HOURS_REQUIRED_DEFAULT,
    add_days,
    add_minutes,
    add_milliseconds,
    advance_clock_to,
    approve_shift,
    assert_volunteer_shift,
    assert_status,
    check_in_shift,
    create_guardian,
    create_season,
    create_volunteer_shift,
    get_success_data,
    make_guardian_headers,
    setup_guardian_with_approved_shifts,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create + check-in shift — PRD §3.7
# ===========================================================================
class TestCheckIn:
    """PRD §3.7: "Checking in is performed only by the owning guardian.
    The check-in is permitted in the window that opens 30 minutes
    before the shift's `scheduled_start` and closes 30 minutes after
    its `scheduled_end`: concretely, the logical clock must be at or
    after `scheduled_start` minus 30 minutes and at or before
    `scheduled_end` plus 30 minutes. A check-in outside that window —
    either too early or too late — is rejected with
    `ERR_CHECK_IN_OUTSIDE_WINDOW`."
    """

    def test_check_in_within_window_succeeds(self, api):
        """PRD §3.7: "the logical clock must be at or after
        `scheduled_start` minus 30 minutes and at or before
        `scheduled_end` plus 30 minutes."

        Claim: check-in at exactly scheduled_start succeeds.
        """
        season = create_season()
        guardian = create_guardian()
        start = "2026-06-01T10:00:00.000Z"
        end = add_minutes(start, 90)
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            scheduled_start=start,
            scheduled_end=end,
        )
        advance_clock_to(start)
        result = check_in_shift(
            shift_id=shift["id"], guardian=guardian,
        )
        assert_status(result, "CHECKED_IN")

    def test_check_in_too_early_rejected(self, api):
        """PRD §3.7: "A check-in outside that window — either too
        early or too late — is rejected with
        `ERR_CHECK_IN_OUTSIDE_WINDOW`."

        Claim: check-in 31 minutes before scheduled_start (outside
        grace window) -> ERR_CHECK_IN_OUTSIDE_WINDOW.
        """
        season = create_season()
        guardian = create_guardian()
        start = "2026-06-01T10:00:00.000Z"
        end = add_minutes(start, 90)
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            scheduled_start=start,
            scheduled_end=end,
        )
        # 31 minutes before start = 09:29.
        advance_clock_to(add_minutes(start, -31))
        resp = api.check_in_shift(
            shift["id"], make_guardian_headers(guardian["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CHECK_IN_OUTSIDE_WINDOW.value,
        )

    def test_check_in_too_late_rejected(self, api):
        """PRD §3.7: "A check-in outside that window — either too
        early or too late — is rejected with
        `ERR_CHECK_IN_OUTSIDE_WINDOW`."

        Claim: check-in 31 minutes after scheduled_end ->
        ERR_CHECK_IN_OUTSIDE_WINDOW.
        """
        season = create_season()
        guardian = create_guardian()
        start = "2026-06-01T10:00:00.000Z"
        end = add_minutes(start, 90)
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            scheduled_start=start,
            scheduled_end=end,
        )
        advance_clock_to(add_minutes(end, 31))
        resp = api.check_in_shift(
            shift["id"], make_guardian_headers(guardian["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CHECK_IN_OUTSIDE_WINDOW.value,
        )

    def test_check_in_by_non_owner_rejected(self, api):
        """PRD §3.7: "Checking in is performed only by the owning
        guardian."
        PRD §2.1: "ownership checks on a `VolunteerShift` compare the
        shift's `guardian_id` to `X-User-ID`".

        Claim: another guardian's headers -> ERR_NOT_OWNER.
        """
        season = create_season()
        owning_guardian = create_guardian()
        other_guardian = create_guardian()
        start = "2026-06-01T10:00:00.000Z"
        end = add_minutes(start, 90)
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=owning_guardian,
            scheduled_start=start,
            scheduled_end=end,
        )
        advance_clock_to(start)
        resp = api.check_in_shift(
            shift["id"], make_guardian_headers(other_guardian["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


# ===========================================================================
# Approve shift — PRD §3.7
# ===========================================================================
class TestApprove:
    """PRD §3.7: "Approving a `CHECKED_IN` shift is the responsibility
    of a `LeagueAdmin` and is only permitted once the logical clock is
    at or beyond the shift's `scheduled_end`. The approval computes
    `hours_credited` as the difference between `scheduled_end` and
    `scheduled_start` expressed in hours (a 90-minute shift credits
    1.50 hours), rounded to two decimal places half-up. The shift's
    `status` flips to `APPROVED`, the owning guardian's
    `volunteer_hours_logged` is recomputed by the guardian-sum rule
    (Section 2.9), and the guardian's `volunteer_status` is reclassified."
    """

    def test_approve_credits_90_minute_shift_as_1_50_hours(self, api):
        """PRD §3.7: "a 90-minute shift credits 1.50 hours".
        PRD §3.7: "The shift's `status` flips to `APPROVED`".

        Claim: 90-minute shift credits hours_credited == 1.50 and
        status == 'APPROVED'.
        """
        season = create_season()
        guardian = create_guardian()
        start = "2026-06-01T10:00:00.000Z"
        end = add_minutes(start, 90)
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            scheduled_start=start,
            scheduled_end=end,
        )
        advance_clock_to(start)
        check_in_shift(shift_id=shift["id"], guardian=guardian)
        advance_clock_to(end)
        result = approve_shift(shift_id=shift["id"])
        assert_status(result, "APPROVED")
        assert result["hours_credited"] == pytest.approx(1.50, abs=0.001)


# ===========================================================================
# Volunteer status thresholds — PRD §2.9
# ===========================================================================
class TestVolunteerStatusThresholds:
    """PRD §2.9: "when `volunteer_hours_logged` is at least
    `volunteer_hours_required_per_family`, the status is `FULFILLED`;
    otherwise, when `volunteer_hours_logged` is at least half of
    `volunteer_hours_required_per_family` (the half-of-required
    boundary is computed at full precision and compared with the
    at-least operator, so a guardian sitting exactly at half the
    required hours is `ON_TRACK`, not `DEFICIENT`), the status is
    `ON_TRACK`; otherwise the status is `DEFICIENT`."
    """

    def test_zero_hours_is_deficient(self, api, league_admin_headers):
        """PRD §3.2: "`volunteer_status` (one of `DEFICIENT`,
        `ON_TRACK`, `FULFILLED`, defaulting to `DEFICIENT`)".

        Claim: a freshly created guardian with no shifts has
        volunteer_status == 'DEFICIENT'.
        """
        guardian = create_guardian()
        # Re-fetch.
        from test_helpers import api_client as ac
        g = get_success_data(
            ac.get_guardian(guardian["id"], league_admin_headers),
        )
        assert g["volunteer_status"] == "DEFICIENT"
        assert float(g["volunteer_hours_logged"]) == 0.0

    def test_on_track_at_exact_half(self, api, league_admin_headers):
        """PRD §2.9: "a guardian sitting exactly at half the required
        hours is `ON_TRACK`, not `DEFICIENT`".

        Claim: with required=6.0, an approved 3.00-hour shift yields
        volunteer_status == 'ON_TRACK'.
        """
        season = create_season(volunteer_hours_required_per_family=6.0)
        # 3.00 hours = 180 minutes.
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[180],
        )
        from test_helpers import api_client as ac
        g = get_success_data(
            ac.get_guardian(guardian["id"], league_admin_headers),
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            3.00, abs=0.001,
        )
        assert g["volunteer_status"] == "ON_TRACK"

    def test_fulfilled_at_required(self, api, league_admin_headers):
        """PRD §2.9: "when `volunteer_hours_logged` is at least
        `volunteer_hours_required_per_family`, the status is
        `FULFILLED`".

        Claim: a guardian whose approved hours equal the required value
        has volunteer_status == 'FULFILLED'.
        """
        season = create_season(volunteer_hours_required_per_family=6.0)
        # Sum of approved hours = 6.0 (one 360-minute shift).
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[360],
        )
        from test_helpers import api_client as ac
        g = get_success_data(
            ac.get_guardian(guardian["id"], league_admin_headers),
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            6.00, abs=0.001,
        )
        assert g["volunteer_status"] == "FULFILLED"

    def test_just_below_half_is_deficient(self, api, league_admin_headers):
        """PRD §2.9: "otherwise the status is `DEFICIENT`."

        Claim: with required=6.0, an approved shift of 2.99 hours (just
        below half) yields volunteer_status == 'DEFICIENT'.
        """
        season = create_season(volunteer_hours_required_per_family=6.0)
        # 2 hours 59 minutes 24 seconds = 2.99 hours
        # 2.99 hours = 179.4 minutes -> use 179 minutes ~ 2.9833 hours
        # (rounds to 2.98 < 3.0). Use 178 minutes = 2.9667 hours -> 2.97.
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[178],
        )
        from test_helpers import api_client as ac
        g = get_success_data(
            ac.get_guardian(guardian["id"], league_admin_headers),
        )
        assert float(g["volunteer_hours_logged"]) < 3.0
        assert g["volunteer_status"] == "DEFICIENT"


# ===========================================================================
# Volunteer hours sum-then-round — PRD §2.9
# ===========================================================================
class TestSumThenRound:
    """PRD §2.9: "The sum is computed at full precision and only the
    final total is rounded to two decimal places using half-up;
    rounding each row before summing would yield different totals when
    individual shifts cover sub-cent fractional hours, and that order
    matters."
    """

    def test_sum_then_round_two_shifts(self, api, league_admin_headers):
        """PRD §2.9: "The sum is computed at full precision and only
        the final total is rounded to two decimal places using
        half-up".

        Claim: a 90-min shift (1.50 hr) plus a 135-min shift (2.25 hr)
        sums to 3.75 hours and yields volunteer_status == 'ON_TRACK'
        (3.75 >= 6.0*0.5 = 3.0, < 6.0).
        """
        season = create_season(volunteer_hours_required_per_family=6.0)
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[90, 135],
        )
        from test_helpers import api_client as ac
        g = get_success_data(
            ac.get_guardian(guardian["id"], league_admin_headers),
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            3.75, abs=0.001,
        )
        assert g["volunteer_status"] == "ON_TRACK"
