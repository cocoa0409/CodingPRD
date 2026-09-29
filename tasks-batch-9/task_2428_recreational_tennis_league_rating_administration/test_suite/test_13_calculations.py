"""Rating arithmetic, the weighted ledger, the two standings bases and the year-end run."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import (
    ERR_FACILITY_COURTS_EXCEEDED,
    ERR_TEAM_DATE_CONFLICT,
)
from test_helpers.constants import (
    APPEAL_SUBMITTED,
    APPEAL_UP,
    INELIGIBLE_PLAYER_SUSPENDED,
    INELIGIBLE_YEAR_END_RECALC,
    PLAYER_ACTIVE,
    PLAYER_DISQUALIFIED,
    PLAYER_STRIKE_SUSPENDED,
    RATING_COMPUTER_RATED,
    RATING_PERIOD_RECALC_IN_PROGRESS,
    RATING_PERIOD_RECALC_PUBLISHED,
    RATING_SOURCE_YEAR_END_RECALC,
    RATING_UNRATED,
    RESULT_PENDING,
    RESULT_REPORTED,
    SCHED_SCHEDULED,
    SCHED_UNSCHEDULED,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_ACTIVE,
    STRIKE_INELIGIBLE_LINEUP,
    STRIKE_NO_SHOW_DEFAULT,
)
from test_helpers.fixtures import (
    SIX_PLAYER_LEAGUE_KWARGS,
    played_match,
    six_a_side_league,
    two_team_league,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


def _ledger_lines(s, first_sets=None):
    """Line 1 carries ``first_sets``; line 2 is a home sweep and line 3 an away sweep."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            first_sets or [f.set_score(6, 4), f.set_score(6, 3)],
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


def _one_verified_match_between_twelve_equal_players(api):
    """Every player is pinned at 3.5, so only the game difference separates them."""
    s = six_a_side_league(
        api,
        ntrp_level=3.5,
        league_kwargs=dict(SIX_PLAYER_LEAGUE_KWARGS, min_active_roster_size=2),
    )
    s.add_player("pbench", full_name="Sid Sideline")
    played_match(s, _ledger_lines(s), match_key="m1")
    return s


def test_one_line_apiece_produces_four_distinct_dynamic_ratings(api):
    """12-7, 12-0, 7-12 and 0-12 against a pinned 3.500 give 3.632, 4.0, 3.368 and 3.0.

    PRD 3.2: "The line's rating is then the pinned opponent level plus 0.50
    multiplied by that game-difference ratio, rounded to three decimals with
    round-half-up."

    Design: Corner/calculations/dynamic_rating_after_one_verified_match_lands_on_six_distinct_pinned_values
    """
    s = _one_verified_match_between_twelve_equal_players(api)

    winner = s.refresh_player("ph1")
    assert winner["dynamic_rating"] == 3.632
    assert winner["rating_level"] == 3.5
    assert winner["rating_type"] == RATING_COMPUTER_RATED
    assert winner["verified_match_count"] == 1
    assert winner["verified_line_count"] == 1

    assert s.refresh_player("ph3")["dynamic_rating"] == 4.000
    assert s.refresh_player("ph5")["dynamic_rating"] == 3.368
    assert s.refresh_player("pa1")["dynamic_rating"] == 3.368
    assert s.refresh_player("pa3")["dynamic_rating"] == 3.000
    assert s.refresh_player("pa5")["dynamic_rating"] == 3.632

    bench = s.refresh_player("pbench")
    assert bench["dynamic_rating"] is None
    assert bench["verified_line_count"] == 0


def test_each_line_rating_is_rounded_before_it_enters_the_mean(api):
    """3.632 and 3.667 average to 3.6495 and round up to 3.650, never to 3.649.

    PRD 3.2: "The rounding order is fixed and not negotiable: each line rating is
    rounded to three decimals *before* it enters the mean, and the mean is rounded
    again afterwards."

    Design: Corner/calculations/dynamic_rating_over_two_lines_rounds_each_line_before_averaging
    """
    s = _one_verified_match_between_twelve_equal_players(api)
    played_match(
        s,
        _ledger_lines(s, [f.set_score(6, 3), f.set_score(6, 3)]),
        match_key="m2",
        start_at="2026-08-22T18:00:00Z",
        end_at="2026-08-22T21:00:00Z",
        round_number=2,
        scorecard_key="sc2",
    )

    twice_played = s.refresh_player("ph1")
    assert twice_played["dynamic_rating"] == 3.650
    assert twice_played["dynamic_rating"] != 3.649
    assert twice_played["verified_match_count"] == 2
    assert twice_played["verified_line_count"] == 2

    sweeper = s.refresh_player("ph3")
    assert sweeper["dynamic_rating"] == 4.000
    assert sweeper["verified_line_count"] == 2

    # 3.368 and 3.333 average to 3.3505, which round-half-up takes to 3.351.
    assert s.refresh_player("pa1")["dynamic_rating"] == 3.351

    home = s.refresh_team("th")
    assert home["matches_won"] == 2
    assert home["lines_won"] == 4
    assert home["standings_points"] == 10


def _six_player_teams_with_a_two_player_minimum(api):
    """Two six-player rosters in a league whose `min_active_roster_size` is 2."""
    return six_a_side_league(
        api,
        league_kwargs=dict(SIX_PLAYER_LEAGUE_KWARGS, min_active_roster_size=2),
    )


def test_a_strike_carries_the_weight_of_its_kind_rather_than_a_count_of_one(api):
    """One INELIGIBLE_LINEUP row moves the ledger by 2 and triggers nothing else.

    PRD 3.7: "An `INELIGIBLE_LINEUP` carries weight 2."

    Design: Corner/calculations/strike_weight_is_taken_from_the_kind_table_not_counted_as_one
    """
    s = _six_player_teams_with_a_two_player_minimum(api)
    strike = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_INELIGIBLE_LINEUP,
                reason="Fielded on an unactivated spot",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    assert strike["kind"] == STRIKE_INELIGIBLE_LINEUP
    assert strike["weight"] == 2
    assert strike["status"] == STRIKE_ACTIVE
    assert strike["match_id"] is None
    assert strike["source_grievance_id"] is None

    charged = s.refresh_player("ph2")
    assert charged["strike_count"] == 2
    assert charged["status"] == PLAYER_ACTIVE

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["ineligible_reason"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 6
    assert team["roster_compliant"] is True


def test_the_lightest_kind_still_carries_the_ledger_across_the_limit(api):
    """2 plus 1 suspends at exactly 3 and stays clear of the disqualification floor.

    PRD 3.7: "If `strike_count` has reached or passed the section's
    `disqualification_strike_limit`, the player's `status` becomes `DISQUALIFIED`,
    which is terminal."

    Design: Corner/calculations/strike_ledger_crossing_the_limit_exactly_suspends_without_disqualifying
    """
    s = _six_player_teams_with_a_two_player_minimum(api)
    get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_INELIGIBLE_LINEUP,
                reason="Fielded on an unactivated spot",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    assert s.refresh_player("ph2")["strike_count"] == 2

    crossing = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_NO_SHOW_DEFAULT,
                reason="Did not appear for the rescheduled fixture",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    assert crossing["weight"] == 1

    charged = s.refresh_player("ph2")
    assert charged["strike_count"] == 3
    assert charged["status"] == PLAYER_STRIKE_SUSPENDED
    assert charged["status"] != PLAYER_DISQUALIFIED

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["ineligible_reason"] == INELIGIBLE_PLAYER_SUSPENDED
    assert spot["source_strike_id"] == crossing["id"]

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 5
    assert team["roster_compliant"] is True
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE


def _item_for(items, team_id):
    """The standings row of ``team_id``."""
    matches = [item for item in items if item["id"] == team_id]
    assert len(matches) == 1
    return matches[0]


def _reported_match_nobody_has_verified(api):
    """A complete three-line card sits at SUBMITTED and the match at REPORTED."""
    s = six_a_side_league(
        api,
        ntrp_level=3.5,
        league_kwargs=dict(SIX_PLAYER_LEAGUE_KWARGS, min_active_roster_size=2),
    )
    played_match(s, _ledger_lines(s), match_key="m1", verify=False)
    return s


def test_the_official_basis_ignores_a_match_that_is_only_reported(api):
    """A full card earns nothing at all until the opposing captain verifies it.

    PRD 3.6: "The official basis counts only `VERIFIED` and `FINALIZED` matches, so
    a match sitting at `REPORTED` but not yet verified contributes nothing at all"

    Design: Corner/calculations/official_standings_ignore_a_reported_but_unverified_match
    """
    s = _reported_match_nobody_has_verified(api)
    response = api.get_standings(
        s.league["id"], LEAGUE_COORDINATOR, {"limit": 100, "offset": 0}
    )
    items, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2

    for team_key in ("th", "ta"):
        row = _item_for(items, s.teams[team_key]["id"])
        assert row["standings_points"] == 0
        assert row["matches_won"] == 0
        assert row["lines_won"] == 0
        assert row["games_won"] == 0

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_REPORTED
    assert match["winner_team_id"] is None

    unrated = s.refresh_player("ph1")
    assert unrated["dynamic_rating"] is None
    assert unrated["verified_line_count"] == 0


def test_the_provisional_basis_credits_the_very_same_reported_match(api):
    """Identical rows, two answers, and the provisional one is never persisted.

    PRD 3.6: "The provisional basis additionally counts matches at `REPORTED`,
    deriving their tentative line, set and game credits and their tentative winner by
    running the line-credit resolution over the scorecard `lines` currently on file."

    Design: Corner/calculations/provisional_standings_basis_credits_the_same_reported_match_the_official_basis_drops
    """
    s = _reported_match_nobody_has_verified(api)
    response = api.get_standings(
        s.league["id"],
        LEAGUE_COORDINATOR,
        {"basis": "provisional", "limit": 100, "offset": 0},
    )
    items, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 2

    home = _item_for(items, s.teams["th"]["id"])
    assert home["standings_points"] == 5
    assert home["matches_won"] == 1
    assert home["lines_won"] == 2
    assert home["sets_won"] == 4
    assert home["games_won"] == 31

    away = _item_for(items, s.teams["ta"]["id"])
    assert away["standings_points"] == 1
    assert away["matches_won"] == 0
    assert away["matches_lost"] == 1
    assert away["lines_won"] == 1
    assert away["games_won"] == 19

    assert s.refresh_team("th")["standings_points"] == 0

    official, _official_meta = validate_paginated(
        api.get_standings(
            s.league["id"],
            LEAGUE_COORDINATOR,
            {"basis": "official", "limit": 100, "offset": 0},
        )
    )
    assert _item_for(official, s.teams["th"]["id"])["standings_points"] == 0
    assert _item_for(official, s.teams["ta"]["id"])["standings_points"] == 0


def test_phase_one_writes_the_proposal_fields_and_nothing_else(api):
    """Twelve proposals are pinned while every live rating field stays put.

    PRD 3.9: "No player's `rating_level`, `rating_type` or `dynamic_rating` moves in
    phase one, and no roster spot moves."

    Design: Corner/calculations/year_end_recalc_writes_only_the_proposal_fields_and_scopes_out_unplayed_players
    """
    s = _one_verified_match_between_twelve_equal_players(api)
    section = get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_IN_PROGRESS
    assert section["recalculated_player_count"] == 12
    assert section["recalc_run_index"] == 0
    assert section["published_level_change_count"] == 0

    promoted = s.refresh_player("ph3")
    assert promoted["proposed_recalc_dynamic"] == 4.000
    assert promoted["proposed_recalc_level"] == 4.0
    assert promoted["rating_level"] == 3.5
    assert promoted["dynamic_rating"] == 4.000
    assert promoted["rating_type"] == RATING_COMPUTER_RATED

    # A delta of 0.132 is below the upward threshold of 0.25.
    held = s.refresh_player("ph1")
    assert held["proposed_recalc_dynamic"] == 3.632
    assert held["proposed_recalc_level"] == 3.5

    # A delta of -0.500 is at or below the downward threshold of -0.35.
    demoted = s.refresh_player("pa3")
    assert demoted["proposed_recalc_dynamic"] == 3.000
    assert demoted["proposed_recalc_level"] == 3.0

    # A delta of -0.132 is above the downward threshold.
    assert s.refresh_player("pa1")["proposed_recalc_level"] == 3.5

    bench = s.refresh_player("pbench")
    assert bench["proposed_recalc_level"] is None
    assert bench["proposed_recalc_dynamic"] is None

    assert s.refresh_spot("ph3")["status"] == SPOT_ACTIVE


def test_phase_two_applies_the_levels_stamps_history_and_evicts_the_promoted_pair(api):
    """Four of twelve levels genuinely move and only the two promotions cost a spot.

    PRD 3.9: "The section's `published_level_change_count` counts only the players
    whose level genuinely changed, so it is generally smaller than
    `recalculated_player_count`."

    Design: Corner/calculations/publish_recalc_applies_levels_stamps_history_and_evicts_the_overrated_pair
    """
    s = _one_verified_match_between_twelve_equal_players(api)
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    section = get_success_data(api.publish_recalc(s.section["id"], SECTION_ADMIN))
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_PUBLISHED
    assert section["recalc_run_index"] == 1
    assert section["published_level_change_count"] == 4
    assert section["recalculated_player_count"] == 12

    promoted = s.refresh_player("ph3")
    assert promoted["rating_level"] == 4.0
    assert promoted["rating_type"] == RATING_COMPUTER_RATED
    assert promoted["dynamic_rating"] == 4.000

    demoted = s.refresh_player("pa3")
    assert demoted["rating_level"] == 3.0
    assert demoted["dynamic_rating"] == 3.000

    unchanged = s.refresh_player("ph1")
    assert unchanged["rating_level"] == 3.5
    entry = unchanged["rating_history"][-1]
    assert entry["source"] == RATING_SOURCE_YEAR_END_RECALC
    assert entry["level"] == 3.5
    assert entry["dynamic_rating"] == 3.632
    assert entry["effective_season_year"] == 2027
    assert_instant_equals(entry["recorded_at"], "2026-08-15T21:00:00Z")

    for key in ("ph3", "ph4"):
        spot = s.refresh_spot(key)
        assert spot["status"] == SPOT_INELIGIBLE
        assert spot["ineligible_reason"] == INELIGIBLE_YEAR_END_RECALC
        assert spot["source_strike_id"] is None

    _away_active, away_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "team_id": s.teams["ta"]["id"],
                "status": SPOT_ACTIVE,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert away_meta["total_count"] == 6

    home = s.refresh_team("th")
    assert home["active_roster_size"] == 4
    assert home["playoff_eligible_roster_size"] == 4
    assert home["roster_compliant"] is True
    assert s.refresh_league()["noncompliant_team_count"] == 0

    bench = s.refresh_player("pbench")
    assert bench["rating_type"] == RATING_UNRATED
    assert bench["rating_level"] is None


def test_a_match_may_be_rescheduled_into_the_slot_it_already_occupies(api):
    """The mover is excluded from both occupancy geometries it is being tested against.

    PRD 3.5: "Both edges enforce the identical rule set; the difference is that on a
    reschedule the match's own prior slot is **excluded** from both geometric checks
    before the new slot is measured, so a match never collides with the slot it is in
    the act of releasing."

    Design: Corner/calculations/reschedule_into_its_own_released_slot_succeeds_at_a_facility_at_exact_capacity
    """
    s = two_team_league(api, roster_size=2)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    scheduled = s.refresh_match("m1")
    assert scheduled["version"] == 2

    again = get_success_data(
        api.schedule_match(
            scheduled["id"],
            f.schedule_payload(
                s.facility["id"], "2026-08-15T18:00:00Z", scheduled["version"], 3
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert again["schedule_status"] == SCHED_SCHEDULED
    assert again["facility_id"] == s.facility["id"]
    assert_instant_equals(again["scheduled_start_at"], "2026-08-15T18:00:00Z")
    assert_instant_equals(again["scheduled_end_at"], "2026-08-15T21:00:00Z")
    assert again["courts_required"] == 3
    assert again["version"] == 3
    assert again["result_status"] == RESULT_PENDING


def test_a_second_fixture_on_the_same_utc_date_is_refused_however_far_apart(api):
    """06:00 and 18:00 share a calendar date, and that alone decides the request.

    PRD 3.5: "When the flag is false, which is the default, the rule is a pure **UTC
    calendar-date bucket**: the request is rejected if any peer's
    `scheduled_start_at` falls on the same UTC calendar date as the requested start."

    Design: Corner/calculations/second_fixture_for_one_team_on_the_same_utc_date_returns_409_team_date_conflict
    """
    s = two_team_league(api, roster_size=2, start=False)
    s.add_player("p3a", level=4.0, full_name="Cal Cross")
    s.add_player("p3b", level=4.0, full_name="Dan Drop")
    s.create_team("tc", "p3a", "Court Crashers")
    s.fill_roster("tc", ["p3a", "p3b"])
    s.register_team("tc")
    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    s.start_play()

    elsewhere = get_success_data(
        api.create_facility(
            f.facility_payload(s.section["id"], name="Sunset Courts", court_count=4),
            SECTION_ADMIN,
        ),
        201,
    )
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.create_match("m3", "th", "tc", round_number=2)

    pending = s.refresh_match("m3")
    assert pending["version"] == 1
    response = api.schedule_match(
        pending["id"],
        f.schedule_payload(
            elsewhere["id"], "2026-08-15T06:00:00Z", pending["version"], 3
        ),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_TEAM_DATE_CONFLICT, 409)
    assert response.json()["data"]["error_id"] != ERR_FACILITY_COURTS_EXCEEDED

    refused = s.refresh_match("m3")
    assert refused["schedule_status"] == SCHED_UNSCHEDULED
    assert refused["facility_id"] is None
    assert refused["scheduled_start_at"] is None
    assert refused["version"] == 1
    assert_instant_equals(s.refresh_match("m1")["scheduled_start_at"], "2026-08-15T18:00:00Z")


def test_a_wide_rating_gap_does_not_auto_qualify_a_one_match_appellant(api):
    """The gap clears 0.300 easily while one verified match falls short of three.

    PRD 3.8: "For an `UP` appeal, `auto_grant_eligible` is true when all three of the
    following hold: the pinned verified match count is at least the required match
    count; the gap is at least the threshold; and the requested level is exactly the
    pinned level plus 0.5."

    Design: Corner/calculations/appeal_auto_grant_verdict_is_false_when_the_match_floor_is_unmet_despite_a_wide_gap
    """
    s = _one_verified_match_between_twelve_equal_players(api)
    appellant = s.refresh_player("ph3")
    assert appellant["rating_type"] == RATING_COMPUTER_RATED

    appeal = get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(
                s.player_id("ph3"),
                APPEAL_UP,
                4.0,
                reason="A 12-0 line against a 3.5 pair shows the level is understated",
            ),
            make_player_headers(s.player_id("ph3")),
        ),
        201,
    )
    assert appeal["status"] == APPEAL_SUBMITTED
    assert appeal["direction"] == APPEAL_UP
    assert appeal["requested_level"] == 4.0
    assert appeal["rating_level_at_filing"] == 3.5
    assert appeal["dynamic_rating_at_filing"] == 4.000
    assert appeal["verified_match_count_at_filing"] == 1
    assert appeal["strike_count_at_filing"] == 0
    assert appeal["auto_grant_eligible"] is False
    assert appeal["support_vote_count"] == 0
    assert appeal["oppose_vote_count"] == 0
    assert appeal["granted_level"] is None
    assert appeal["decided_by_chair_player_id"] is None
