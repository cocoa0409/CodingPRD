"""Endpoint-shaped behaviour: the 204 removal, action endpoints and computed reads."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_instant_equals
from test_helpers.api_errors import ERR_NOT_FOUND, ERR_RECALC_PHASE_INVALID
from test_helpers.constants import (
    AGE_18_OVER,
    CLOCK_DEFAULT,
    CREDIT_SOURCE_TEAM_DEFAULT,
    DEFAULT_KIND_NO_SHOW,
    FORMAT_MENS_DOUBLES,
    INELIGIBLE_YEAR_END_RECALC,
    RATING_COMPUTER_RATED,
    RATING_PERIOD_RECALC_PUBLISHED,
    RATING_SOURCE_YEAR_END_RECALC,
    RATING_UNRATED,
    RESULT_DISPUTED,
    RESULT_VERIFIED,
    REVIEW_DISPUTE,
    SCHED_DEFAULTED,
    SCHED_PLAYED,
    SCORECARD_DISPUTED,
    SIDE_HOME,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    SPOT_PENDING,
    SPOT_REMOVED,
    STRIKE_NO_SHOW_DEFAULT,
    SURFACE_CLAY,
    SURFACE_HARD,
    TIER_SECTION,
)
from test_helpers.fixtures import (
    SIX_PLAYER_LEAGUE_KWARGS,
    Scenario,
    played_match,
    six_a_side_league,
    standard_three_lines,
    two_team_league,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


def _draft_team_with_one_active_and_one_pending_spot(api):
    """Team H is DRAFT in an open league: ph1 activated, ph2 still pending."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section(min_matches_for_playoff_eligibility=1)
    s.create_facility()
    s.create_league(
        tier=TIER_SECTION,
        ntrp_level=4.0,
        age_group=AGE_18_OVER,
        format=FORMAT_MENS_DOUBLES,
        min_active_roster_size=2,
    )
    s.open_registration()
    s.add_player("ph1", level=4.0, full_name="Hank Halfvolley")
    s.add_player("ph2", level=4.0, full_name="Ned Netcord")
    s.create_team("th", "ph1", "Balboa Aces")
    s.add_spot("th", "ph1")
    s.activate_spot("th", "ph1")
    s.add_spot("th", "ph2")
    return s


def test_removing_a_pending_spot_answers_204_and_keeps_the_row_as_removed(api):
    """The only empty-bodied response in the surface, and the row survives.

    PRD 3.3: "Captain-driven removal takes a spot from `PENDING` or `ACTIVE` to
    `REMOVED`, which is terminal."

    Design: Corner/endpoints/captain_removal_of_a_pending_spot_returns_204_and_the_spot_leaves_every_list
    """
    s = _draft_team_with_one_active_and_one_pending_spot(api)
    before = s.team_version("th")

    response = api.delete_roster_spot(
        s.spots["ph2"]["id"], s.captain_headers("th")
    )
    assert response.status_code == 204
    assert response.text == ""

    removed = s.refresh_spot("ph2")
    assert removed["status"] == SPOT_REMOVED
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE

    active, active_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "team_id": s.teams["th"]["id"],
                "status": SPOT_ACTIVE,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert active_meta["total_count"] == 1
    assert active[0]["player_id"] == s.player_id("ph1")

    _pending, pending_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "team_id": s.teams["th"]["id"],
                "status": SPOT_PENDING,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert pending_meta["total_count"] == 0

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 1
    assert team["version"] == before + 1


# ---------------------------------------------------------------------------
def _home_side_no_show(api):
    """A scheduled fixture that the home side never turns up for."""
    s = two_team_league(api, roster_size=2)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.set_clock("2026-08-15T21:00:00Z")
    return s


def test_recording_a_home_default_credits_every_line_to_the_away_side(api):
    """One action moves both dimensions, synthesises three lines and issues a strike.

    PRD 3.6: "Every line from 1 to the line count - *including lines that were
    actually played* - is credited to the away side at the standard default line
    score, with `credit_source` `TEAM_DEFAULT`."

    Design: Corner/endpoints/recording_a_home_default_credits_every_line_to_away_and_strikes_the_home_captain
    """
    s = _home_side_no_show(api)
    defaulted = get_success_data(
        api.default_match(
            s.matches["m1"]["id"],
            f.default_payload(
                SIDE_HOME,
                DEFAULT_KIND_NO_SHOW,
                note="Home side did not appear at the facility",
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert defaulted["schedule_status"] == SCHED_DEFAULTED
    assert defaulted["result_status"] == RESULT_VERIFIED
    assert defaulted["default_side"] == SIDE_HOME
    assert defaulted["default_kind"] == DEFAULT_KIND_NO_SHOW
    assert defaulted["winner_team_id"] == s.teams["ta"]["id"]
    assert defaulted["home_lines_won"] == 0
    assert defaulted["away_lines_won"] == 3
    assert defaulted["home_sets_won"] == 0
    assert defaulted["away_sets_won"] == 6
    assert defaulted["home_games_won"] == 0
    assert defaulted["away_games_won"] == 36
    assert_instant_equals(defaulted["verified_at"], "2026-08-15T21:00:00Z")

    assert len(defaulted["line_results"]) == 3
    for entry in defaulted["line_results"]:
        assert entry["credit_source"] == CREDIT_SOURCE_TEAM_DEFAULT
        assert entry["credited_to"] == s.teams["ta"]["id"]
        assert entry["home_sets"] == 0
        assert entry["away_sets"] == 2
        assert entry["home_games"] == 0
        assert entry["away_games"] == 12

    _cards, card_meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert card_meta["total_count"] == 0


def test_only_the_defaulting_sides_captain_is_struck_by_the_default(api):
    """The single synthesised strike weighs 1 and points back at the match.

    PRD 3.6: "One strike of kind `NO_SHOW_DEFAULT` is issued to the captain of each
    defaulting side, so a `BOTH` default issues two strikes - one to each captain."

    Design: Corner/endpoints/recording_a_home_default_credits_every_line_to_away_and_strikes_the_home_captain
    """
    s = _home_side_no_show(api)
    s.default_match("m1", SIDE_HOME, DEFAULT_KIND_NO_SHOW)

    struck, struck_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {"player_id": s.player_id("ph1"), "limit": 100, "offset": 0},
        )
    )
    assert struck_meta["total_count"] == 1
    assert struck[0]["kind"] == STRIKE_NO_SHOW_DEFAULT
    assert struck[0]["weight"] == 1
    assert struck[0]["match_id"] == s.matches["m1"]["id"]

    _spared, spared_meta = validate_paginated(
        api.list_strikes(
            SECTION_ADMIN,
            {"player_id": s.player_id("pa1"), "limit": 100, "offset": 0},
        )
    )
    assert spared_meta["total_count"] == 0

    winner = s.refresh_team("ta")
    assert winner["matches_won"] == 1
    assert winner["lines_won"] == 3
    assert winner["games_won"] == 36
    assert winner["standings_points"] == 6

    loser = s.refresh_team("th")
    assert loser["matches_lost"] == 1
    assert loser["lines_won"] == 0
    assert loser["standings_points"] == 0


# ---------------------------------------------------------------------------
def test_the_facilities_sub_resource_follows_the_foreign_key_not_the_caller(api):
    """Two sections own courts; the listing returns exactly one section's own.

    PRD 3.1: "The facilities of a section can be listed as a filtered collection,
    narrowable by `surface`."

    Design: Corner/endpoints/section_facilities_sub_resource_returns_only_its_own_sections_courts
    """
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    home_hard = s.create_facility(court_count=6, surface=SURFACE_HARD)
    home_clay = s.create_facility(
        name="Kern Clay Annex", court_count=2, surface=SURFACE_CLAY
    )
    other = get_success_data(
        api.create_section(
            f.section_payload(code="NORCAL-2026", name="Northern California"),
            SECTION_ADMIN,
        ),
        201,
    )
    foreign = s.create_facility(
        section_id=other["id"],
        name="Bay Area Courts",
        court_count=4,
        surface=SURFACE_CLAY,
    )

    items, meta = validate_paginated(
        api.list_section_facilities(s.section["id"], LEAGUE_COORDINATOR)
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert {item["id"] for item in items} == {home_hard["id"], home_clay["id"]}
    assert foreign["id"] not in {item["id"] for item in items}
    for item in items:
        assert item["section_id"] == s.section["id"]

    clay, clay_meta = validate_paginated(
        api.list_section_facilities(
            s.section["id"], LEAGUE_COORDINATOR, {"surface": SURFACE_CLAY}
        )
    )
    assert clay_meta["total_count"] == 1
    assert clay[0]["id"] == home_clay["id"]

    theirs, theirs_meta = validate_paginated(
        api.list_section_facilities(other["id"], LEAGUE_COORDINATOR)
    )
    assert theirs_meta["total_count"] == 1
    assert theirs[0]["id"] == foreign["id"]

    validate_error(
        api.list_section_facilities(NON_EXISTENT_UUID, LEAGUE_COORDINATOR),
        ERR_NOT_FOUND,
        404,
    )


# ---------------------------------------------------------------------------
def test_the_standings_read_ranks_the_default_winner_first_and_writes_nothing(api):
    """Creation order would put the loser first; the ranking keys must not.

    PRD 3.9: "The first key is `standings_points` descending, read on the official
    basis only - the provisional basis of §3.6 never seeds anything."

    Design: Corner/endpoints/standings_read_orders_the_default_winner_ahead_of_the_earlier_created_loser
    """
    s = _home_side_no_show(api)
    s.default_match("m1", SIDE_HOME, DEFAULT_KIND_NO_SHOW)
    winner_version = s.refresh_team("ta")["version"]

    rows, meta = validate_paginated(
        api.get_standings(s.league["id"], make_player_headers(s.player_id("pa1")))
    )
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    assert rows[0]["id"] == s.teams["ta"]["id"]
    assert rows[0]["standings_points"] == 6
    assert rows[0]["matches_won"] == 1
    assert rows[0]["lines_won"] == 3
    assert rows[0]["sets_won"] == 6
    assert rows[0]["games_won"] == 36

    assert rows[1]["id"] == s.teams["th"]["id"]
    assert rows[1]["standings_points"] == 0
    assert rows[1]["matches_won"] == 0
    assert rows[1]["matches_lost"] == 1
    assert rows[1]["lines_won"] == 0
    assert rows[1]["games_won"] == 0

    # A read persists nothing.
    assert s.refresh_team("ta")["version"] == winner_version

    provisional, _pmeta = validate_paginated(
        api.get_standings(
            s.league["id"],
            make_player_headers(s.player_id("pa1")),
            {"basis": "provisional"},
        )
    )
    assert [row["id"] for row in provisional] == [
        s.teams["ta"]["id"],
        s.teams["th"]["id"],
    ]
    assert provisional[0]["standings_points"] == 6

    first_page, first_meta = validate_paginated(
        api.get_standings(
            s.league["id"],
            make_player_headers(s.player_id("pa1")),
            {"limit": 1, "offset": 0},
        )
    )
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert [row["id"] for row in first_page] == [s.teams["ta"]["id"]]


# ---------------------------------------------------------------------------
TWELVE_RATED = ["ph1", "ph2", "ph3", "ph4", "ph5", "ph6",
                "pa1", "pa2", "pa3", "pa4", "pa5", "pa6"]


def _twelve_pinned_proposals_and_one_out_of_scope_player(api):
    """One verified match rates twelve players; a thirteenth never played a line."""
    s = six_a_side_league(
        api,
        ntrp_level=3.5,
        league_kwargs=dict(SIX_PLAYER_LEAGUE_KWARGS, min_active_roster_size=2),
    )
    s.add_player("pa7", full_name="Sid Sideline")
    played_match(
        s,
        [
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
        ],
        match_key="m1",
    )
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))
    return s


def test_publishing_a_recalculation_reports_two_different_bulk_counters(api):
    """Twelve players were evaluated and only four levels actually moved.

    PRD 3.1: "`recalculated_player_count` records how many players had a proposed
    level written by the most recent year-end recalculation run, and
    `published_level_change_count` records how many players' `rating_level`
    actually changed when that run was published."

    Design: Corner/endpoints/publish_recalc_is_all_or_nothing_across_twelve_players_and_cannot_run_twice
    """
    s = _twelve_pinned_proposals_and_one_out_of_scope_player(api)
    published = get_success_data(api.publish_recalc(s.section["id"], SECTION_ADMIN))
    assert published["recalculated_player_count"] == 12
    assert published["published_level_change_count"] == 4
    assert published["published_level_change_count"] != published[
        "recalculated_player_count"
    ]
    assert published["rating_period_status"] == RATING_PERIOD_RECALC_PUBLISHED
    assert published["recalc_run_index"] == 1

    _rated, rated_meta = validate_paginated(
        api.list_players(
            SECTION_ADMIN,
            {
                "section_id": s.section["id"],
                "rating_type": RATING_COMPUTER_RATED,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert rated_meta["total_count"] == 12

    for key in TWELVE_RATED:
        history = s.refresh_player(key)["rating_history"]
        assert history[-1]["source"] == RATING_SOURCE_YEAR_END_RECALC
        assert history[-1]["effective_season_year"] == 2027

    evicted, evicted_meta = validate_paginated(
        api.list_roster_spots(
            SECTION_ADMIN,
            {
                "ineligible_reason": INELIGIBLE_YEAR_END_RECALC,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert evicted_meta["total_count"] == 2
    for spot in evicted:
        assert spot["team_id"] == s.teams["th"]["id"]
        assert spot["status"] == SPOT_INELIGIBLE


def test_a_published_recalculation_cannot_be_published_a_second_time(api):
    """The posture gate closes behind the publish, and the run index holds at 1.

    PRD 2.2: "Beginning a recalculation requires the section to be at `OPEN_SEASON`,
    and publishing one requires the section to be at `RECALC_IN_PROGRESS`; a
    request that arrives against the wrong posture is refused with
    `ERR_RECALC_PHASE_INVALID` (HTTP 409)."

    Design: Corner/endpoints/publish_recalc_is_all_or_nothing_across_twelve_players_and_cannot_run_twice
    """
    s = _twelve_pinned_proposals_and_one_out_of_scope_player(api)
    get_success_data(api.publish_recalc(s.section["id"], SECTION_ADMIN))

    validate_error(
        api.publish_recalc(s.section["id"], SECTION_ADMIN),
        ERR_RECALC_PHASE_INVALID,
        409,
    )
    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["recalc_run_index"] == 1
    assert section["rating_period_status"] == RATING_PERIOD_RECALC_PUBLISHED

    bystander = s.refresh_player("pa7")
    assert bystander["rating_type"] == RATING_UNRATED
    assert bystander["proposed_recalc_level"] is None
    assert bystander["rating_history"] == []


# ---------------------------------------------------------------------------
def _submitted_card_awaiting_review(api):
    """The home side's three-line card sits SUBMITTED and the match is REPORTED."""
    s = six_a_side_league(api)
    played_match(s, standard_three_lines(s), match_key="m1", verify=False)
    return s


def test_a_disputing_review_withdraws_the_result_from_both_bases(api):
    """The provisional five points vanish and none of the verify cascade runs.

    PRD 3.6: "A `DISPUTE` decision takes the scorecard from `SUBMITTED` or from
    `AMENDED` to `DISPUTED`, and takes the match's `result_status` from `REPORTED`
    to `DISPUTED`."

    Design: Corner/endpoints/review_with_dispute_withdraws_the_result_from_both_standings_bases
    """
    s = _submitted_card_awaiting_review(api)
    before, _meta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    assert _row_for(before, s.teams["th"]["id"])["standings_points"] == 5

    disputed = get_success_data(
        api.review_scorecard(
            s.scorecards["sc1"]["id"],
            {
                "decision": REVIEW_DISPUTE,
                "dispute_reason": "Line 3 set scores are transposed",
                "disputed_line_numbers": [3],
            },
            s.captain_headers("ta"),
        )
    )
    assert disputed["status"] == SCORECARD_DISPUTED
    assert disputed["dispute_reason"] == "Line 3 set scores are transposed"
    assert disputed["disputed_line_numbers"] == [3]
    assert disputed["verified_at"] is None
    assert disputed["verified_by_captain_player_id"] is None
    assert disputed["amendment_count"] == 0

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_DISPUTED
    assert match["schedule_status"] == SCHED_PLAYED
    assert match["winner_team_id"] is None
    assert match["home_lines_won"] == 0
    assert match["away_lines_won"] == 0
    assert match["line_results"] == []

    official, _official_meta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN)
    )
    provisional, _provisional_meta = validate_paginated(
        api.get_standings(s.league["id"], SECTION_ADMIN, {"basis": "provisional"})
    )
    for rows in (official, provisional):
        for team_key in ("th", "ta"):
            assert _row_for(rows, s.teams[team_key]["id"])["standings_points"] == 0

    captain = s.refresh_player("ph1")
    assert captain["dynamic_rating"] is None
    assert captain["verified_match_count"] == 0
    assert captain["verified_line_count"] == 0

    spot = s.refresh_spot("ph1")
    assert spot["verified_match_count"] == 0
    assert spot["playoff_eligible"] is False


def _row_for(rows, team_id):
    for row in rows:
        if row["id"] == team_id:
            return row
    raise AssertionError(f"team {team_id} missing from the standings page")
