"""Game scheduling, field overlap, opponent constraints, season window.

PRD §3.4 (scheduling) and PRD §2.7 (field booking) drive this file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GAME_DURATION_MINUTES,
    TEST_DEFAULTS,
    add_minutes,
    advance_clock_to,
    advance_to_regular_season,
    assert_game,
    assert_status,
    create_game_payload,
    create_season,
    create_team,
    create_coach,
    parse_iso,
    schedule_game,
    setup_regular_season,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create game — basic shape + computed fields
# ===========================================================================
class TestScheduleGame:
    """PRD §3.4: "A regular-season `Game` is scheduled by a
    `LeagueAdmin`."
    """

    def test_schedule_game_happy_path(self, api):
        """PRD §3.4: "The server fixes `scheduled_end` as
        `scheduled_start` plus 90 minutes and snapshots the start as
        `original_scheduled_start`".

        Claim: created Game.scheduled_end == start + 90 minutes;
        Game.original_scheduled_start == scheduled_start;
        Game.status == 'SCHEDULED'.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=start,
        )
        assert_game(g)
        assert_status(g, "SCHEDULED")
        assert g["scheduled_start"] == start
        assert g["original_scheduled_start"] == start
        # scheduled_end is start + 90 minutes.
        expected_end = add_minutes(start, GAME_DURATION_MINUTES)
        assert g["scheduled_end"] == expected_end, (
            f"scheduled_end must be start+90min, got {g['scheduled_end']!r}, "
            f"expected {expected_end!r}"
        )
        assert g["referee_id"] is None
        assert g["home_score"] is None
        assert g["away_score"] is None
        assert g["bracket_round"] is None

    def test_same_team_opponents_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "The two team identifiers must be different —
        equal opponents surface as `ERR_INVALID_GAME_OPPONENTS`".

        Claim: home_team_id == away_team_id -> ERR_INVALID_GAME_OPPONENTS.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[0]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_INVALID_GAME_OPPONENTS.value,
        )

    def test_game_outside_regular_window_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "the `scheduled_start` of a regular game must fall
        inside the season's regular-season window (from
        `regular_season_start` at midnight UTC of that calendar day
        through `regular_season_end` at 23:59:59.999 UTC of that
        calendar day), with a date outside the window rejected as
        `ERR_GAME_OUT_OF_SEASON_WINDOW`."

        Claim: REGULAR game scheduled outside [regular_season_start,
        regular_season_end] -> ERR_GAME_OUT_OF_SEASON_WINDOW.
        """
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8,
            season_overrides={
                "regular_season_start": "2026-05-01T00:00:00.000Z",
                "regular_season_end": "2026-07-31T23:59:59.999Z",
            },
        )
        teams = bundle["teams"]
        season = bundle["season"]
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-04-30T23:59:59.000Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_GAME_OUT_OF_SEASON_WINDOW.value,
        )


# ===========================================================================
# Field overlap — PRD §2.7
# ===========================================================================
class TestFieldOverlap:
    """PRD §2.7: "Two slots on the same `field_id` are considered to
    collide if and only if one's start is strictly earlier than the
    other's end and vice versa; slots that exactly touch at the
    boundary — for example, `[10:00, 11:30)` followed by
    `[11:30, 13:00)` — do not collide and are both permitted."
    """

    def test_overlapping_games_on_same_field_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §2.7: "Two slots on the same `field_id` are considered
        to collide if and only if one's start is strictly earlier than
        the other's end and vice versa". PRD §2.7: "A collision
        surfaces as `ERR_FIELD_OVERLAP`."

        Claim: a second game whose start falls inside the first's
        window on the SAME field -> ERR_FIELD_OVERLAP.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:00:00.000Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FIELD_OVERLAP.value)

    def test_touching_boundary_is_allowed(
        self, api, league_admin_headers,
    ):
        """PRD §2.7: "slots that exactly touch at the boundary — for
        example, `[10:00, 11:30)` followed by `[11:30, 13:00)` — do not
        collide and are both permitted."

        Claim: second game starting at exact end of first on SAME field
        succeeds (touching at the half-open boundary is allowed).
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:30:00.000Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["scheduled_start"] == "2026-05-10T11:30:00.000Z"

    def test_field_overlap_one_ms_before_boundary_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §2.7: "Two slots on the same `field_id` are considered
        to collide if and only if one's start is strictly earlier than
        the other's end and vice versa".

        Claim: scheduled_start one millisecond before the existing
        scheduled_end -> ERR_FIELD_OVERLAP (strict less-than violated).
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        # The first game ends at 11:30:00.000. One ms before is
        # 11:29:59.999.
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:29:59.999Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FIELD_OVERLAP.value)

    def test_different_field_no_overlap(
        self, api, league_admin_headers,
    ):
        """PRD §2.7: "Two slots on the same `field_id`" — the overlap
        rule only applies to identical field_ids.

        Claim: identical window on a DIFFERENT field_id is permitted.
        """
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        resp = api.create_game(payload, league_admin_headers)
        data = validate_success(resp, expected_status=201)
        # field_id round-trips the value the server actually stored
        # (the test_suite conftest applies a per-test salt for test
        # isolation, so we assert "F2" is the suffix rather than the
        # bare value).
        assert data["field_id"].endswith("F2")
