"""Concurrency, OCC, and PRD-stated race outcomes.

PRD §2.4 defines optimistic concurrency via `version`.
PRD §3.4 names the referee-assignment race and the reschedule race.
PRD §3.3 names the draft-pick races.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assign_referee_payload,
    assign_referee_to_game,
    create_referee,
    record_result_payload,
    record_game_result,
    run_race,
    schedule_game,
    setup_regular_season,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# OCC — PRD §2.4
# ===========================================================================
class TestOccVersionConflict:
    """PRD §2.4: "When a client supplies it, the server compares the
    supplied integer to the current `version` of the target row: a
    match allows the mutation to proceed and the `version` is
    incremented in the same transaction; a mismatch causes the request
    to be rejected with `ERR_VERSION_CONFLICT` and HTTP 409 without
    any side effect being applied."
    """

    def test_assign_referee_stale_version_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §2.4: "a mismatch causes the request to be rejected with
        `ERR_VERSION_CONFLICT` and HTTP 409 without any side effect
        being applied."

        Claim: supplying an outdated `version` to assign-referee
        returns ERR_VERSION_CONFLICT.
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
        stale_version = g["version"] - 1
        resp = api.assign_referee(
            g["id"],
            assign_referee_payload(
                referee_id=ref["id"], version=stale_version,
            ),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# Race — assign-referee — PRD §3.4
# ===========================================================================
class TestAssignRefereeRace:
    """PRD §3.4: "Two operators attempting to assign referees to the
    same game at the same time serialize on a compare-and-set against
    `Game.referee_id`: exactly one assignment lands, and the loser is
    rejected with `ERR_GAME_REFEREE_ALREADY_ASSIGNED`."
    """

    def test_concurrent_assign_referee_exactly_one_wins(
        self, api, league_admin_headers,
    ):
        """PRD §3.4: "Two operators attempting to assign referees to
        the same game at the same time serialize on a compare-and-set
        against `Game.referee_id`: exactly one assignment lands, and
        the loser is rejected with
        `ERR_GAME_REFEREE_ALREADY_ASSIGNED`."

        Claim: two concurrent assign-referee calls on the same null-
        referee game produce exactly one success and one
        ERR_GAME_REFEREE_ALREADY_ASSIGNED failure.
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

        def assign_one():
            return api.assign_referee(
                g["id"],
                assign_referee_payload(referee_id=ref1["id"]),
                league_admin_headers,
            )

        def assign_two():
            return api.assign_referee(
                g["id"],
                assign_referee_payload(referee_id=ref2["id"]),
                league_admin_headers,
            )

        results = run_race(assign_one, assign_two)
        # PRD names the loser's error_id explicitly:
        # ERR_GAME_REFEREE_ALREADY_ASSIGNED. Use assert_exactly_one_succeeds
        # to get the loser's response and verify its error_id.
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # `outcome` is a dict with "successes" and "failures" lists.
        failure_resps = outcome["failures"]
        assert len(failure_resps) == 1
        # Inspect the loser's error_id.
        loser_body = failure_resps[0].json()
        loser_error_id = loser_body.get("data", {}).get("error_id")
        assert loser_error_id == ApiErrorId.ERR_GAME_REFEREE_ALREADY_ASSIGNED.value, (
            "Loser must surface ERR_GAME_REFEREE_ALREADY_ASSIGNED, got "
            f"{loser_error_id!r}"
        )
