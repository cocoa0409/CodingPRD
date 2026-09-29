"""The official and provisional standings bases, and the moment they converge."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.constants import (
    RESULT_DISPUTED,
    RESULT_REPORTED,
    RESULT_VERIFIED,
    REVIEW_DISPUTE,
    REVIEW_VERIFY,
    SCORECARD_VERIFIED,
)
from test_helpers.fixtures import played_match, six_a_side_league
from test_helpers.test_users import SECTION_ADMIN


def _first_match_card(s):
    """Home takes lines 1 and 2 (6-4 6-3, 6-0 6-0); away takes line 3 (4-6 3-6)."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 4), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
    ]


def _second_match_card(s):
    """The same shape one week later (6-3 6-3, 6-0 6-0, 4-6 3-6): 31 games to 18."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(6, 3), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
    ]


def _one_verified_match_and_one_reported_match(api):
    """Round 1 is VERIFIED; round 2 sits at REPORTED with the away captain silent."""
    s = six_a_side_league(
        api, section_kwargs={"min_matches_for_playoff_eligibility": 1}
    )
    played_match(s, _first_match_card(s), match_key="m1", round_number=1)
    played_match(
        s,
        _second_match_card(s),
        match_key="m2",
        start_at="2026-08-22T18:00:00Z",
        end_at="2026-08-22T21:00:00Z",
        round_number=2,
        verify=False,
        scorecard_key="sc2",
    )
    return s


def _row_for(rows, team_id):
    for row in rows:
        if row["id"] == team_id:
            return row
    raise AssertionError(f"team {team_id} missing from the standings page")


def test_the_two_bases_diverge_by_exactly_the_reported_match(api):
    """One stored row set, two answers, and the gap is the tentative credit itself.

    PRD 3.9: "The provisional basis additionally counts matches at `REPORTED`,
    deriving their tentative line, set and game credits and their tentative winner by
    running the line-credit resolution over the scorecard `lines` currently on file."

    Design: Corner/cross_cutting_complexity_layers/provisional_and_official_standings_diverge_by_exactly_the_reported_match
    """
    s = _one_verified_match_and_one_reported_match(api)
    home_id = s.teams["th"]["id"]
    away_id = s.teams["ta"]["id"]

    rows, meta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert meta["total_count"] == 2
    assert rows[0]["id"] == home_id

    home = _row_for(rows, home_id)
    assert home["matches_won"] == 2
    assert home["matches_lost"] == 0
    assert home["lines_won"] == 4
    assert home["lines_lost"] == 2
    assert home["sets_won"] == 8
    assert home["sets_lost"] == 4
    assert home["games_won"] == 62
    assert home["games_lost"] == 37
    assert home["standings_points"] == 10

    away = _row_for(rows, away_id)
    assert away["matches_won"] == 0
    assert away["matches_lost"] == 2
    assert away["lines_won"] == 2
    assert away["lines_lost"] == 4
    assert away["sets_won"] == 4
    assert away["sets_lost"] == 8
    assert away["games_won"] == 37
    assert away["games_lost"] == 62
    assert away["standings_points"] == 2

    official, _ometa = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    official_home = _row_for(official, home_id)
    official_away = _row_for(official, away_id)
    assert official_home["standings_points"] == 5
    assert official_away["standings_points"] == 1

    # The delta is exactly the second match's tentative credit.
    assert home["standings_points"] - official_home["standings_points"] == 5
    assert home["matches_won"] - official_home["matches_won"] == 1
    assert home["lines_won"] - official_home["lines_won"] == 2
    assert home["sets_won"] - official_home["sets_won"] == 4
    assert home["games_won"] - official_home["games_won"] == 31
    assert away["standings_points"] - official_away["standings_points"] == 1
    assert away["matches_lost"] - official_away["matches_lost"] == 1
    assert away["lines_won"] - official_away["lines_won"] == 1

    # The persisted fields carry the official basis; the provisional read wrote nothing.
    assert s.refresh_team("th")["standings_points"] == 5
    reported = s.refresh_match("m2")
    assert reported["result_status"] == RESULT_REPORTED
    assert reported["winner_team_id"] is None
    assert reported["home_lines_won"] == 0


def test_verifying_the_second_card_lands_the_official_basis_on_the_earlier_forecast(api):
    """The forecast becomes the record, counted once and not twice.

    PRD 3.9: "The official basis counts only `VERIFIED` and `FINALIZED` matches, so a
    match sitting at `REPORTED` but not yet verified contributes nothing at all; the
    official basis is also the *only* basis the playoff seeding of §3.9 ever reads."

    Design: Corner/cross_cutting_complexity_layers/verifying_the_second_card_closes_the_gap_between_the_two_bases_exactly
    """
    s = _one_verified_match_and_one_reported_match(api)
    home_id = s.teams["th"]["id"]
    away_id = s.teams["ta"]["id"]
    forecast, _fmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert _row_for(forecast, home_id)["standings_points"] == 10

    verified = get_success_data(
        api.review_scorecard(
            s.scorecards["sc2"]["id"],
            {"decision": REVIEW_VERIFY},
            s.captain_headers("ta"),
        )
    )
    assert verified["status"] == SCORECARD_VERIFIED

    match = s.refresh_match("m2")
    assert match["result_status"] == RESULT_VERIFIED
    assert match["home_lines_won"] == 2
    assert match["away_lines_won"] == 1
    assert match["home_sets_won"] == 4
    assert match["away_sets_won"] == 2
    assert match["home_games_won"] == 31
    assert match["away_games_won"] == 18
    assert match["winner_team_id"] == home_id

    official, _ometa = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    provisional, _pmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    for rows in (official, provisional):
        assert _row_for(rows, home_id)["standings_points"] == 10
        assert _row_for(rows, away_id)["standings_points"] == 2

    home = s.refresh_team("th")
    assert home["matches_won"] == 2
    assert home["lines_won"] == 4
    assert home["sets_won"] == 8
    assert home["games_won"] == 62
    assert home["standings_points"] == 10

    away = s.refresh_team("ta")
    assert home["matches_won"] + home["matches_lost"] + away["matches_won"] + away[
        "matches_lost"
    ] == 4
    assert home["lines_won"] + away["lines_won"] == 6
    assert home["lines_lost"] + away["lines_lost"] == 6
    assert home["sets_won"] + away["sets_won"] == 12
    assert home["games_won"] + away["games_won"] == 99
    assert home["games_lost"] + away["games_lost"] == 99
    assert home["standings_points"] + away["standings_points"] == 12

    spots, spots_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN, {"team_id": home_id, "limit": 100, "offset": 0}
        )
    )
    assert spots_meta["total_count"] == 6
    for spot in spots:
        assert spot["verified_match_count"] == 2


def test_disputing_the_second_card_returns_both_bases_to_the_first_match(api):
    """A DISPUTED match is outside both inclusion sets, so the gap closes downward.

    PRD 3.9: "The counted match set for a team is the matches of the team's league
    naming that team on either side whose `result_status` falls in the basis's
    inclusion set."

    Design: Corner/cross_cutting_complexity_layers/verifying_the_second_card_closes_the_gap_between_the_two_bases_exactly
    """
    s = _one_verified_match_and_one_reported_match(api)
    home_id = s.teams["th"]["id"]
    away_id = s.teams["ta"]["id"]

    get_success_data(
        api.review_scorecard(
            s.scorecards["sc2"]["id"],
            {
                "decision": REVIEW_DISPUTE,
                "dispute_reason": "Line 1 set scores were transposed",
                "disputed_line_numbers": [1],
            },
            s.captain_headers("ta"),
        )
    )
    assert s.refresh_match("m2")["result_status"] == RESULT_DISPUTED

    official, _ometa = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    provisional, _pmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    for rows in (official, provisional):
        assert _row_for(rows, home_id)["standings_points"] == 5
        assert _row_for(rows, away_id)["standings_points"] == 1
        assert _row_for(rows, home_id)["matches_won"] == 1
        assert _row_for(rows, home_id)["games_won"] == 31

    assert s.refresh_team("th")["standings_points"] == 5
