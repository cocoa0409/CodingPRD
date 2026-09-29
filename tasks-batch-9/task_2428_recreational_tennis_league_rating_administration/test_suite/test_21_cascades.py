"""Multi-level cascades: verification, strike issuance, and a refused default."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_MATCH_NOT_YET_PLAYABLE,
    ERR_MATCH_SCHEDULE_STATE_INVALID,
    ERR_ROSTER_QUOTA_NOT_MET,
)
from test_helpers.constants import (
    DEFAULT_KIND_NO_SHOW,
    INELIGIBLE_PLAYER_SUSPENDED,
    PLAYER_ACTIVE,
    PLAYER_STRIKE_SUSPENDED,
    RESULT_PENDING,
    RESULT_VERIFIED,
    REVIEW_VERIFY,
    SCHED_CONFIRMED,
    SCHED_DEFAULTED,
    SCHED_PLAYED,
    SCORECARD_VERIFIED,
    SIDE_HOME,
    SPOT_INELIGIBLE,
    STRIKE_ACTIVE,
    STRIKE_NO_SHOW_DEFAULT,
    STRIKE_SCORECARD_FALSIFICATION,
)
from test_helpers.fixtures import (
    played_match,
    six_a_side_league,
    two_team_league,
)
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN

SIX_A_SIDE_KEYS = ("ph1", "ph2", "ph3", "ph4", "ph5", "ph6")
AWAY_SIX_KEYS = ("pa1", "pa2", "pa3", "pa4", "pa5", "pa6")


def _reported_six_a_side_card(s):
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


def _card_awaiting_the_away_captains_review(api):
    """Twelve named players, one PLAYED match, one SUBMITTED card."""
    s = six_a_side_league(
        api, section_kwargs={"min_matches_for_playoff_eligibility": 1}
    )
    played_match(s, _reported_six_a_side_card(s), match_key="m1", verify=False)
    return s


def test_one_verification_moves_the_match_and_both_team_ledgers_together(api):
    """A single accepted review has to land the card, the match and the standings.

    PRD 3.6: "At the second level, both teams recompute `matches_won`,
    `matches_lost`, `lines_won`, `lines_lost`, `sets_won`, `sets_lost`, `games_won`,
    `games_lost` and `standings_points` on the official basis."

    Design: Corner/cross_cutting_complexity_layers/verifying_one_scorecard_walks_the_whole_chain_from_card_to_league_counters
    """
    s = _card_awaiting_the_away_captains_review(api)
    card_id = s.scorecards["sc1"]["id"]
    home_version = s.refresh_team("th")["version"]
    away_version = s.refresh_team("ta")["version"]

    verified = get_success_data(
        api.review_scorecard(
            card_id, {"decision": REVIEW_VERIFY}, s.captain_headers("ta")
        )
    )
    assert verified["status"] == SCORECARD_VERIFIED
    assert_instant_equals(verified["verified_at"], "2026-08-15T21:00:00Z")
    assert verified["verified_by_captain_player_id"] == s.player_id("pa1")

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_VERIFIED
    assert match["schedule_status"] == SCHED_PLAYED
    assert match["winner_team_id"] == s.teams["th"]["id"]
    assert match["home_lines_won"] == 2
    assert match["away_lines_won"] == 1
    assert match["home_sets_won"] == 4
    assert match["away_sets_won"] == 2
    assert match["home_games_won"] == 31
    assert match["away_games_won"] == 19

    home = s.refresh_team("th")
    assert home["matches_won"] == 1
    assert home["matches_lost"] == 0
    assert home["lines_won"] == 2
    assert home["lines_lost"] == 1
    assert home["sets_won"] == 4
    assert home["sets_lost"] == 2
    assert home["games_won"] == 31
    assert home["games_lost"] == 19
    assert home["standings_points"] == 5
    assert home["playoff_eligible_roster_size"] == 6

    away = s.refresh_team("ta")
    assert away["matches_won"] == 0
    assert away["matches_lost"] == 1
    assert away["lines_won"] == 1
    assert away["lines_lost"] == 2
    assert away["sets_won"] == 2
    assert away["sets_lost"] == 4
    assert away["games_won"] == 19
    assert away["games_lost"] == 31
    assert away["standings_points"] == 1

    # The ledger closes on itself across the two sides of the one match.
    assert home["matches_won"] + home["matches_lost"] + away["matches_won"] + away[
        "matches_lost"
    ] == 2
    assert home["lines_won"] + away["lines_won"] == home["lines_lost"] + away[
        "lines_lost"
    ] == 3
    assert home["sets_won"] + away["sets_won"] == home["sets_lost"] + away[
        "sets_lost"
    ] == 6
    assert home["games_won"] + away["games_won"] == 50
    assert home["standings_points"] + away["standings_points"] == 6

    assert home["version"] > home_version
    assert away["version"] > away_version

    # The card has left REPORTED, so it can no longer be reviewed.
    replay = api.review_scorecard(
        card_id, {"decision": REVIEW_VERIFY}, s.captain_headers("ta")
    )
    assert replay.status_code == 409


def test_the_same_verification_credits_all_twelve_players_and_their_spots(api):
    """Levels three and four reach every named player and every matching spot.

    PRD 3.6: "At the fourth level, every corresponding roster spot recomputes its own
    `verified_match_count` and its `playoff_eligible` flag."

    Design: Corner/cross_cutting_complexity_layers/verifying_one_scorecard_walks_the_whole_chain_from_card_to_league_counters
    """
    s = _card_awaiting_the_away_captains_review(api)
    get_success_data(
        api.review_scorecard(
            s.scorecards["sc1"]["id"],
            {"decision": REVIEW_VERIFY},
            s.captain_headers("ta"),
        )
    )

    for team_key in ("th", "ta"):
        spots, meta = validate_paginated(
            api.list_roster_spots(
                SECTION_ADMIN,
                {"team_id": s.teams[team_key]["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 6
        for spot in spots:
            assert spot["verified_match_count"] == 1
            assert spot["playoff_eligible"] is True

    for key in SIX_A_SIDE_KEYS + AWAY_SIX_KEYS:
        player = s.refresh_player(key)
        assert player["verified_match_count"] == 1
        assert player["verified_line_count"] == 1
        assert player["dynamic_rating"] is not None

    rows, _meta = validate_paginated(api.get_standings(s.league["id"], SECTION_ADMIN))
    assert rows[0]["id"] == s.teams["th"]["id"]
    assert rows[0]["standings_points"] == 5

    # Nothing is left in REPORTED, so the two bases agree exactly.
    provisional, _pmeta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert [row["id"] for row in provisional] == [row["id"] for row in rows]
    assert [row["standings_points"] for row in provisional] == [
        row["standings_points"] for row in rows
    ]


# ---------------------------------------------------------------------------
def _two_registered_teams_at_the_compliance_floor(api):
    """Both squads hold exactly min_active_roster_size ACTIVE spots and are compliant."""
    s = two_team_league(api, roster_size=2, with_committee=True, start=False)
    assert s.refresh_team("th")["roster_compliant"] is True
    assert s.refresh_team("ta")["roster_compliant"] is True
    return s


def test_one_strike_reorders_the_player_the_spot_the_team_and_the_league(api):
    """The recompute order is the point: ledger, then status, then spot, then team.

    PRD 3.7: "Suspension cascades into roster composition. When a player crosses into
    `STRIKE_SUSPENDED`, every roster spot of that player at `ACTIVE` transitions to
    `INELIGIBLE` with `ineligible_reason` set to `PLAYER_SUSPENDED` and
    `source_strike_id` set to the identifier of the strike that just crossed the
    threshold."

    Design: Corner/cross_cutting_complexity_layers/one_strike_reorders_player_roster_team_and_league_counters_in_that_order
    """
    s = _two_registered_teams_at_the_compliance_floor(api)
    home_version = s.refresh_team("th")["version"]
    away_version = s.refresh_team("ta")["version"]

    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_SCORECARD_FALSIFICATION,
                reason="Falsified a set score on a prior card",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    assert strike["weight"] == 3
    assert strike["status"] == STRIKE_ACTIVE
    assert strike["version"] == 1
    assert strike["match_id"] is None

    struck = s.refresh_player("ph2")
    assert struck["strike_count"] == 3
    assert struck["status"] == PLAYER_STRIKE_SUSPENDED

    ledger, ledger_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN, {"player_id": s.player_id("ph2"), "limit": 100, "offset": 0}
        )
    )
    assert ledger_meta["total_count"] == 1
    assert ledger[0]["id"] == strike["id"]

    demoted, demoted_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {"player_id": s.player_id("ph2"), "limit": 100, "offset": 0},
        )
    )
    assert demoted_meta["total_count"] == 1
    assert demoted[0]["status"] == SPOT_INELIGIBLE
    assert demoted[0]["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert demoted[0]["source_strike_id"] == strike["id"]

    home = s.refresh_team("th")
    assert home["active_roster_size"] == 1
    assert home["roster_compliant"] is False
    assert home["version"] == home_version + 1

    # PRD 3.1 counts only "teams of this league in the roster-locked or in-play
    # states whose `roster_compliant` is false", and both teams are REGISTERED here.
    league = get_success_data(api.get_league(s.league["id"], SECTION_ADMIN))
    assert league["noncompliant_team_count"] == 0
    assert league["registered_team_count"] == 2

    untouched = s.refresh_team("ta")
    assert untouched["active_roster_size"] == 2
    assert untouched["roster_compliant"] is True
    assert untouched["version"] == away_version

    # Roster lock counts registered teams; starting play counts compliant ones.
    s.set_clock("2026-08-08T00:00:00Z")
    locked = get_success_data(api.lock_rosters(s.league["id"], LEAGUE_COORDINATOR))
    # The stranded team locks anyway and is now counted as noncompliant (PRD 3.4).
    assert locked["noncompliant_team_count"] == 1
    validate_error(
        api.start_play(s.league["id"], LEAGUE_COORDINATOR),
        ERR_ROSTER_QUOTA_NOT_MET,
        409,
    )


# ---------------------------------------------------------------------------
def _confirmed_fixture_that_has_not_started_yet(api):
    """Fixture 1 is CONFIRMED for 18:00 while the clock still reads 2026-08-10."""
    s = two_team_league(api, roster_size=2)
    s.set_clock("2026-08-10T00:00:00Z")
    s.create_match("m1", "th", "ta")
    creation_version = s.matches["m1"]["version"]
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    return s, creation_version


def test_a_premature_default_writes_none_of_its_three_effects(api):
    """One refusal has to suppress the credits, the strike and the standings alike.

    PRD 3.6: "It takes the match's `schedule_status` from `SCHEDULED` or from
    `CONFIRMED` to `DEFAULTED`, and requires that the current instant has reached
    `scheduled_start_at` and that `result_status` is still `PENDING`."

    Design: Corner/cross_cutting_complexity_layers/a_default_refused_before_its_start_time_returns_422_and_leaves_all_three_effects_unwritten
    """
    s, creation_version = _confirmed_fixture_that_has_not_started_yet(api)
    payload = f.default_payload(
        SIDE_HOME, DEFAULT_KIND_NO_SHOW, note="Home side is not expected to appear"
    )
    home_version = s.refresh_team("th")["version"]
    away_version = s.refresh_team("ta")["version"]

    response = api.default_match(
        s.matches["m1"]["id"], payload, LEAGUE_COORDINATOR
    )
    validate_error(response, ERR_MATCH_NOT_YET_PLAYABLE, 422)
    # CONFIRMED to DEFAULTED is a permitted transition.
    assert response.json()["data"]["error_id"] != ERR_MATCH_SCHEDULE_STATE_INVALID

    match = s.refresh_match("m1")
    assert match["schedule_status"] == SCHED_CONFIRMED
    assert match["result_status"] == RESULT_PENDING
    assert match["default_kind"] is None
    assert match["default_side"] is None
    assert match["winner_team_id"] is None
    assert match["home_lines_won"] == 0
    assert match["version"] == creation_version + 2

    _strikes, strike_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert strike_meta["total_count"] == 0
    captain = s.refresh_player("ph1")
    assert captain["strike_count"] == 0
    assert captain["status"] == PLAYER_ACTIVE

    for team_key, before in (("th", home_version), ("ta", away_version)):
        team = s.refresh_team(team_key)
        assert team["standings_points"] == 0
        assert team["matches_won"] == 0
        assert team["matches_lost"] == 0
        assert team["version"] == before

    # The clock was the only obstacle.
    s.set_clock("2026-08-15T18:00:00Z")
    defaulted = get_success_data(
        api.default_match(s.matches["m1"]["id"], payload, LEAGUE_COORDINATOR)
    )
    assert defaulted["schedule_status"] == SCHED_DEFAULTED
    assert defaulted["result_status"] == RESULT_VERIFIED
    issued, issued_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {"player_id": s.player_id("ph1"), "limit": 100, "offset": 0},
        )
    )
    assert issued_meta["total_count"] == 1
    assert issued[0]["kind"] == STRIKE_NO_SHOW_DEFAULT
    assert issued[0]["weight"] == 1
