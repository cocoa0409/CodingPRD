"""Postpone, reschedule, cancel (rainout window).

PRD §2.7 and §3.4 drive this file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    add_days,
    add_milliseconds,
    add_minutes,
    advance_clock_to,
    assert_game,
    assert_status,
    assign_referee_to_game,
    create_referee,
    create_volunteer_shift,
    create_guardian,
    cancel_game_payload,
    postpone_game,
    postpone_payload,
    reschedule_game,
    reschedule_payload,
    schedule_game,
    setup_regular_season,
    validate_error,
    validate_success,
)


# ===========================================================================
# Postpone — PRD §3.4
# ===========================================================================
class TestPostpone:
    """PRD §3.4: "Postponing a `SCHEDULED` game requires the season to
    be in either `REGULAR_SEASON` or `PLAYOFFS` and a `reason` from the
    set { `RAIN`, `FIELD_UNAVAILABLE`, `SAFETY` }".
    """

    def test_postpone_succeeds(self, api):
        """PRD §3.4: "the game's `status` becomes `POSTPONED`."
        PRD §3.4: "`referee_id` is nulled so the referee is freed for
        that slot".

        Claim: postpone flips status to POSTPONED and nulls referee_id.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=10)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        result = postpone_game(game_id=g["id"], reason="RAIN")
        assert_status(result, "POSTPONED")
        assert result.get("referee_id") is None, (
            "referee_id must be nulled by postpone, got "
            f"{result.get('referee_id')!r}"
        )


# ===========================================================================
# Reschedule — PRD §2.7 + §3.4
# ===========================================================================
class TestReschedule:
    """PRD §3.4: "Rescheduling moves a `POSTPONED` game back to
    `SCHEDULED`. The body supplies a new `scheduled_start` (strictly
    greater than the snapshotted `original_scheduled_start` and no
    later than `original_scheduled_start` plus `rainout_window_days`
    days; both boundaries are enforced and a violation is
    `ERR_RAINOUT_WINDOW_EXCEEDED`)".
    """

    def test_reschedule_happy_path(self, api):
        """PRD §3.4: "Rescheduling moves a `POSTPONED` game back to
        `SCHEDULED`."
        PRD §3.4: "`scheduled_end` is recomputed as the new start plus
        90 minutes; `original_scheduled_start` is preserved across the
        reschedule."

        Claim: reschedule succeeds, status -> SCHEDULED,
        original_scheduled_start preserved, scheduled_end = start + 90.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        new_start = "2026-05-15T18:00:00.000Z"
        result = reschedule_game(
            game_id=g["id"], scheduled_start=new_start,
        )
        assert_status(result, "SCHEDULED")
        assert result["scheduled_start"] == new_start
        assert result["original_scheduled_start"] == original_start
        assert result["scheduled_end"] == add_minutes(new_start, 90)

    def test_reschedule_before_original_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "strictly greater than the snapshotted
        `original_scheduled_start`".

        Claim: new_start == original_scheduled_start (not strict) ->
        ERR_RAINOUT_WINDOW_EXCEEDED.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        resp = api.reschedule_game(
            g["id"],
            reschedule_payload(scheduled_start=original_start),
            league_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_RAINOUT_WINDOW_EXCEEDED.value,
        )

    def test_reschedule_beyond_rainout_window_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "no later than `original_scheduled_start` plus
        `rainout_window_days` days; both boundaries are enforced and a
        violation is `ERR_RAINOUT_WINDOW_EXCEEDED`."

        Claim: new_start > original + rainout_window_days ->
        ERR_RAINOUT_WINDOW_EXCEEDED.
        """
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8, rainout_window_days=14,
        )
        teams = bundle["teams"]
        season = bundle["season"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        # 15 days later — beyond 14-day window.
        too_late = add_days(original_start, 15)
        resp = api.reschedule_game(
            g["id"],
            reschedule_payload(scheduled_start=too_late),
            league_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_RAINOUT_WINDOW_EXCEEDED.value,
        )


# ===========================================================================
# Cancel — PRD §3.4
# ===========================================================================
class TestCancelPostponedGame:
    """PRD §3.4: "Cancelling a `POSTPONED` game is permitted only after
    the rainout window has elapsed — that is, the logical clock is
    strictly later than `original_scheduled_start` plus
    `rainout_window_days` days."
    """

    def test_cancel_before_window_elapsed_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "Cancelling a `POSTPONED` game is permitted only
        after the rainout window has elapsed — that is, the logical
        clock is strictly later than `original_scheduled_start` plus
        `rainout_window_days` days."

        Claim: clock at exactly original_start + rainout_window_days ->
        not strictly later, so cancel rejects (use ERR_INVALID_STATE).
        """
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8, rainout_window_days=14,
        )
        teams = bundle["teams"]
        season = bundle["season"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        # Clock at exactly the boundary (not strictly later).
        advance_clock_to(add_days(original_start, 14))
        resp = api.cancel_game(g["id"], league_admin_headers)
        # PRD names "strictly later"; the generic state error is the
        # acceptable surface (Silence-pattern would otherwise hide
        # this). Use validate_error_is_one_of for safety since PRD
        # does not pin which error_id surfaces for "rainout not yet
        # elapsed" on cancel.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value],
        )

    def test_cancel_after_window_elapsed_succeeds(self, api):
        """PRD §3.4: "The transition simply flips `status` to
        `CANCELLED`".

        Claim: with clock strictly later than original + rainout_days,
        cancel transitions Game.status -> CANCELLED.
        """
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8, rainout_window_days=14,
        )
        teams = bundle["teams"]
        season = bundle["season"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        advance_clock_to(add_milliseconds(add_days(original_start, 14), 1))
        from test_helpers import api_client as ac, TEST_USERS, get_success_data
        result = get_success_data(
            ac.cancel_game(
                g["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert_status(result, "CANCELLED")
