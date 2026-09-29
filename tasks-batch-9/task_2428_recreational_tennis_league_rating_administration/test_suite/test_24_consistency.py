"""Read-your-writes: the response body and the first read that follows must agree."""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    CREDIT_SOURCE_TEAM_DEFAULT,
    DEFAULT_KIND_NO_SHOW,
    PLAYER_ACTIVE,
    RESULT_REPORTED,
    RESULT_VERIFIED,
    SCHED_DEFAULTED,
    SCORECARD_SUBMITTED,
    SIDE_HOME,
    SPOT_ACTIVE,
    STRIKE_ACTIVE,
    STRIKE_NO_SHOW_DEFAULT,
)
from test_helpers.fixtures import six_a_side_league, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


def _played_match_with_no_card_yet(api):
    """Twelve ACTIVE spots, one PLAYED fixture, and an empty scorecard index."""
    s = six_a_side_league(
        api, section_kwargs={"min_matches_for_playoff_eligibility": 1}
    )
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    return s


def _three_line_card(s):
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


def _row_for(rows, team_id):
    for row in rows:
        if row["id"] == team_id:
            return row
    raise AssertionError(f"team {team_id} missing from the standings page")


def test_a_submitted_card_is_already_visible_on_the_very_next_read(api):
    """The write's own body is authoritative and the first read repeats it exactly.

    PRD 2.11: "Cascades are applied within the same request as the action that
    triggered them, so a caller never observes a half-propagated state."

    Design: Corner/consistency_model/a_submitted_card_is_visible_everywhere_on_the_very_next_read
    """
    s = _played_match_with_no_card_yet(api)
    match_id = s.matches["m1"]["id"]
    version_before = s.refresh_match("m1")["version"]

    written = get_success_data(
        api.create_scorecard(
            f.scorecard_payload(match_id, _three_line_card(s)),
            s.captain_headers("th"),
        ),
        201,
    )
    assert written["status"] == SCORECARD_SUBMITTED
    assert written["amendment_count"] == 0
    assert written["version"] == 1
    assert written["submitted_by_captain_player_id"] == s.player_id("ph1")
    assert written["submitted_by_team_id"] == s.teams["th"]["id"]
    assert written["verified_by_captain_player_id"] is None
    assert written["verified_at"] is None
    assert [line["line_number"] for line in written["lines"]] == [1, 2, 3]

    first_read = get_success_data(api.get_scorecard(written["id"], SECTION_ADMIN))
    assert first_read == written

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_REPORTED
    assert match["version"] == version_before + 1

    indexed, indexed_meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN, {"match_id": match_id, "limit": 100, "offset": 0}
        )
    )
    assert indexed_meta["total_count"] == 1
    assert indexed[0]["id"] == written["id"]

    provisional, _pmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert _row_for(provisional, s.teams["th"]["id"])["standings_points"] == 5
    assert _row_for(provisional, s.teams["ta"]["id"])["standings_points"] == 1

    official, _ometa = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    assert _row_for(official, s.teams["th"]["id"])["standings_points"] == 0
    assert _row_for(official, s.teams["ta"]["id"])["standings_points"] == 0
    assert s.refresh_team("th")["standings_points"] == 0

    # Nothing converges after the fact: the second round of reads is identical.
    assert get_success_data(api.get_scorecard(written["id"], SECTION_ADMIN)) == written
    assert s.refresh_match("m1")["version"] == version_before + 1
    repeat, _rmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert _row_for(repeat, s.teams["th"]["id"])["standings_points"] == 5


# ---------------------------------------------------------------------------
def _confirmed_fixture_past_its_start(api):
    """Fixture 1 is CONFIRMED and the clock has moved past its scheduled start."""
    s = two_team_league(api, roster_size=2)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    return s


def test_a_recorded_default_fans_out_to_five_surfaces_with_no_lag(api):
    """The widest single request in the domain, observed on its first read.

    PRD 2.11: "Every entity a cascade touches has its `updated_at` refreshed and its
    `version` increased by 1, even when the client never named that entity."

    Design: Corner/consistency_model/a_default_fans_out_to_five_entity_types_with_no_read_after_write_lag
    """
    s = _confirmed_fixture_past_its_start(api)
    match_id = s.matches["m1"]["id"]

    defaulted = get_success_data(
        api.default_match(
            match_id,
            f.default_payload(
                SIDE_HOME, DEFAULT_KIND_NO_SHOW, note="Home side never appeared"
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert defaulted["schedule_status"] == SCHED_DEFAULTED
    assert defaulted["result_status"] == RESULT_VERIFIED
    assert_instant_equals(defaulted["verified_at"], "2026-08-15T21:00:00Z")
    assert defaulted["default_side"] == SIDE_HOME
    assert defaulted["default_kind"] == DEFAULT_KIND_NO_SHOW
    assert defaulted["winner_team_id"] == s.teams["ta"]["id"]
    assert defaulted["away_lines_won"] == 3
    assert defaulted["away_sets_won"] == 6
    assert defaulted["away_games_won"] == 36
    assert defaulted["home_lines_won"] == 0
    assert defaulted["home_games_won"] == 0
    assert len(defaulted["line_results"]) == 3
    for entry in defaulted["line_results"]:
        assert entry["credit_source"] == CREDIT_SOURCE_TEAM_DEFAULT

    struck, struck_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN, {"match_id": match_id, "limit": 100, "offset": 0}
        )
    )
    assert struck_meta["total_count"] == 1
    assert struck[0]["kind"] == STRIKE_NO_SHOW_DEFAULT
    assert struck[0]["weight"] == 1
    assert struck[0]["player_id"] == s.player_id("ph1")
    assert struck[0]["status"] == STRIKE_ACTIVE

    captain = s.refresh_player("ph1")
    assert captain["strike_count"] == 1
    assert captain["status"] == PLAYER_ACTIVE

    winner = s.refresh_team("ta")
    assert winner["matches_won"] == 1
    assert winner["lines_won"] == 3
    assert winner["sets_won"] == 6
    assert winner["games_won"] == 36
    assert winner["standings_points"] == 6
    loser = s.refresh_team("th")
    assert loser["matches_lost"] == 1
    assert loser["lines_won"] == 0
    assert loser["games_won"] == 0
    assert loser["games_lost"] == 36
    assert loser["standings_points"] == 0

    official, _ometa = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    assert official[0]["id"] == s.teams["ta"]["id"]
    assert official[0]["standings_points"] == 6
    provisional, _pmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert [row["id"] for row in provisional] == [row["id"] for row in official]
    assert _row_for(provisional, s.teams["ta"]["id"])["standings_points"] == 6

    # The ledger closes on that first observation.
    assert winner["matches_won"] + loser["matches_lost"] == 2
    assert winner["lines_won"] + loser["lines_won"] == 3
    assert winner["lines_lost"] + loser["lines_lost"] == 3
    assert winner["sets_won"] + loser["sets_won"] == 6
    assert winner["games_won"] + loser["games_won"] == 36
    assert winner["standings_points"] + loser["standings_points"] == 6

    spots, spots_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"team_id": s.teams["th"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert spots_meta["total_count"] == 2
    for spot in spots:
        assert spot["status"] == SPOT_ACTIVE
        assert spot["verified_match_count"] == 0

    assert s.refresh_match("m1")["result_status"] == RESULT_VERIFIED
    assert s.refresh_team("ta")["standings_points"] == 6
    repeat, _rmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    assert [row["standings_points"] for row in repeat] == [
        row["standings_points"] for row in official
    ]

    replay = api.default_match(
        match_id,
        f.default_payload(SIDE_HOME, DEFAULT_KIND_NO_SHOW),
        LEAGUE_COORDINATOR,
    )
    assert replay.status_code == 409
    assert s.refresh_player("ph1")["strike_count"] == 1
