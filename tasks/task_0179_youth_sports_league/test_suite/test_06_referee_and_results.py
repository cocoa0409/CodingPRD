"""Referee buffer + weekly cap, record-result, forfeit.

PRD §2.8 (referee booking) and §3.5 (game day) drive this file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    REFEREE_BUFFER_MINUTES,
    add_minutes,
    advance_clock_to,
    assert_game,
    assert_status,
    assert_team_games_played_invariant,
    assign_referee_payload,
    assign_referee_to_game,
    create_referee,
    forfeit_payload,
    forfeit_game,
    record_game_result,
    record_result_payload,
    schedule_game,
    setup_regular_season,
    validate_error,
    validate_success,
)


# ===========================================================================
# Assign-referee — PRD §3.4 + §2.8
# ===========================================================================
class TestAssignReferee:
    """PRD §3.4: "Assigning a referee transitions occur at a separate
    endpoint and require the game to currently have `referee_id` of
    null."
    """

    def test_assign_referee_happy_path(self, api, league_admin_headers):
        """PRD §3.4: "Assigning a referee transitions occur at a
        separate endpoint and require the game to currently have
        `referee_id` of null."

        Claim: assign-referee on a null-referee SCHEDULED game succeeds.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee()
        game = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        resp = api.assign_referee(
            game["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        data = validate_success(resp)
        assert data["referee_id"] == ref["id"]

    def test_referee_buffer_within_30_minutes_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §2.8: "A referee may not be assigned to two games whose
        90-minute slots overlap once a 30-minute buffer is added on
        either side of any existing assignment. ... A collision
        surfaces as `ERR_REFEREE_OVERLAP`."

        Claim: a referee assigned to a game ending at 11:30 cannot be
        assigned to another game starting 29 minutes later (within the
        30-minute buffer). ERR_REFEREE_OVERLAP.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=10)
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])

        # g2 starts 29 minutes after g1.scheduled_end (11:30) = 11:59
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T11:59:00.000Z",
        )
        resp = api.assign_referee(
            g2["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFEREE_OVERLAP.value)

    def test_referee_buffer_30_minutes_exact_allowed(
        self, api, league_admin_headers,
    ):
        """PRD §2.8: "a candidate slot `[new_start, new_end)` collides
        with an existing assignment `[a, b)` ... when `new_start` is
        strictly earlier than `b + 30 minutes` and at the same time
        `a − 30 minutes` is strictly earlier than `new_end`."

        Claim: a referee assigned to a game ending at 11:30 CAN be
        assigned to another game starting EXACTLY 30 minutes later
        (boundary at expanded edge is NOT a collision under strict
        less-than).
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=10)
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])

        # g2 starts EXACTLY 30 minutes after g1.scheduled_end (12:00).
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T12:00:00.000Z",
        )
        resp = api.assign_referee(
            g2["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        data = validate_success(resp)
        assert data["referee_id"] == ref["id"]

    def test_referee_weekly_cap_exceeded(self, api, league_admin_headers):
        """PRD §2.8: "if assigning would push the count above the cap,
        the request is rejected with `ERR_REFEREE_WEEKLY_CAP_EXCEEDED`."

        Claim: referee with cap=1 already at 1 assignment in the ISO
        week -> second assignment fails with
        ERR_REFEREE_WEEKLY_CAP_EXCEEDED.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=1)
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-04T18:00:00.000Z",  # Monday
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])
        # Place g2 far enough away that interval-overlap doesn't bite
        # but still in the SAME ISO week (2026-05-04 .. 2026-05-10).
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-08T18:00:00.000Z",
        )
        resp = api.assign_referee(
            g2["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REFEREE_WEEKLY_CAP_EXCEEDED.value,
        )

    def test_double_assign_same_game_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "Assigning a referee transitions occur at a
        separate endpoint and require the game to currently have
        `referee_id` of null."

        Claim: assign-referee on a game that already has a referee ->
        ERR_GAME_REFEREE_ALREADY_ASSIGNED.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref1 = create_referee(weekly_assignment_cap=10)
        ref2 = create_referee(weekly_assignment_cap=10)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref1["id"])
        # Second attempt — different referee, same game.
        resp = api.assign_referee(
            g["id"],
            assign_referee_payload(referee_id=ref2["id"]),
            league_admin_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_GAME_REFEREE_ALREADY_ASSIGNED.value,
        )


# ===========================================================================
# Record result — PRD §3.5
# ===========================================================================
class TestRecordResult:
    """PRD §3.5: "Recording the result of a `SCHEDULED` game requires
    several preconditions to coincide. ... On success, the scores are
    written, `status` flips to `COMPLETED`, and the team-record
    aggregates are recomputed: the winning team's `wins` is incremented
    by one and the losing team's `losses` is incremented by one."
    """

    def test_record_result_happy_path_updates_team_record(self, api):
        """PRD §3.5: "On success, the scores are written, `status` flips
        to `COMPLETED`, and the team-record aggregates are recomputed:
        the winning team's `wins` is incremented by one and the losing
        team's `losses` is incremented by one."

        Claim: home wins 7-3; Game.status COMPLETED, home team wins +1,
        away team losses +1.
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
        result = record_game_result(
            game_id=g["id"],
            home_score=7,
            away_score=3,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        assert_status(result, "COMPLETED")
        assert result["home_score"] == 7
        assert result["away_score"] == 3
        # Inspect both teams' records.
        from test_helpers import api_client as ac, TEST_USERS
        h = TEST_USERS["league_admin_headers"]
        from test_helpers import get_success_data
        home_team = get_success_data(ac.get_team(teams[0]["id"], h))
        away_team = get_success_data(ac.get_team(teams[1]["id"], h))
        assert home_team["wins"] == 1, (
            f"home wins after record-result must be 1, got "
            f"{home_team['wins']}"
        )
        assert home_team["losses"] == 0
        assert away_team["wins"] == 0
        assert away_team["losses"] == 1

    def test_record_result_without_referee_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "The game's `referee_id` must be non-null at the
        moment of recording — a missing referee surfaces as
        `ERR_GAME_REFEREE_REQUIRED`."

        Claim: record-result on a game with referee_id == null ->
        ERR_GAME_REFEREE_REQUIRED.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        advance_clock_to("2026-05-10T19:30:00.000Z")
        resp = api.record_result(
            g["id"],
            record_result_payload(home_score=5, away_score=3),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_GAME_REFEREE_REQUIRED.value)

    @pytest.mark.parametrize(
        "home_score,away_score",
        [
            (3, 3),     # tie
            (-1, 2),    # negative home
            (2, -1),    # negative away
        ],
    )
    def test_invalid_score_rejected(
        self, api, league_admin_headers, home_score, away_score,
    ):
        """PRD §3.5: "ties are not permitted in Little League, so
        `home_score` and `away_score` must differ — an invalid pair (a
        negative score or equal scores) surfaces as `ERR_INVALID_SCORE`."

        Claim: ties and negative scores -> ERR_INVALID_SCORE.
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
        advance_clock_to("2026-05-10T19:30:00.000Z")
        resp = api.record_result(
            g["id"],
            record_result_payload(
                home_score=home_score, away_score=away_score,
            ),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SCORE.value)


# ===========================================================================
# Forfeit — PRD §3.5
# ===========================================================================
class TestForfeit:
    """PRD §3.5: "Forfeiting a `SCHEDULED` game is a separate transition
    driven by a `LeagueAdmin` ... On success, the game's `status`
    becomes `FORFEITED`; the non-forfeiting team is awarded the win
    (its `wins` increments by one) and the forfeiting team takes the
    loss (its `losses` increments by one)."
    """

    def test_forfeit_awards_non_forfeiting_team(self, api):
        """PRD §3.5: "On success, the game's `status` becomes
        `FORFEITED`; the non-forfeiting team is awarded the win (its
        `wins` increments by one) and the forfeiting team takes the
        loss (its `losses` increments by one)."

        Claim: forfeit by away team awards home team the win.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        result = forfeit_game(
            game_id=g["id"], forfeiting_team_id=teams[1]["id"],
        )
        assert_status(result, "FORFEITED")
        from test_helpers import api_client as ac, TEST_USERS
        h = TEST_USERS["league_admin_headers"]
        from test_helpers import get_success_data
        home_team = get_success_data(ac.get_team(teams[0]["id"], h))
        away_team = get_success_data(ac.get_team(teams[1]["id"], h))
        assert home_team["wins"] == 1
        assert away_team["losses"] == 1
