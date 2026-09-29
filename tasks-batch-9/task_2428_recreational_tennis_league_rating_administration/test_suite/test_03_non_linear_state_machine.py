"""Cyclic, two-dimensional and counter-bounded lifecycles."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AMENDMENT_LIMIT_REACHED,
    ERR_SCORECARD_STATE_FORBIDS_ACTION,
)
from test_helpers.constants import (
    LEAGUE_REGISTRATION_OPEN,
    LEAGUE_ROSTERS_LOCKED,
    RESULT_DISPUTED,
    RESULT_PENDING,
    RESULT_REPORTED,
    REVIEW_DISPUTE,
    SCHED_CANCELLED,
    SCHED_PLAYED,
    SCHED_SCHEDULED,
    SCORECARD_AMENDED,
    SCORECARD_DISPUTED,
    SCORECARD_SUBMITTED,
    SPOT_ACTIVE,
    SPOT_REMOVED,
    TEAM_REGISTERED,
    TEAM_ROSTER_LOCKED,
    TEAM_WITHDRAWN,
)
from test_helpers.fixtures import six_a_side_league, two_team_league
from test_helpers.test_users import SECTION_ADMIN


def _three_lines(s, first_sets):
    """Standard three-line card whose line 1 carries ``first_sets``."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            first_sets,
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 4), f.set_score(6, 3)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(4, 6)],
        ),
    ]


def _played_match_with_a_submitted_card(api):
    """M1 at PLAYED / REPORTED with a SUBMITTED card, clock frozen at 21:00Z."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    s.submit_scorecard("m1", _three_lines(s, [f.set_score(6, 4), f.set_score(6, 0)]))
    return s


# ---------------------------------------------------------------------------
# Instance: match_result_dimension_cycles_while_schedule_dimension_stays_played
# ---------------------------------------------------------------------------
def test_result_status_returns_to_reported_while_schedule_status_never_moves(api):
    """PENDING to REPORTED to DISPUTED to REPORTED, all at schedule PLAYED.

    PRD 3.6: "**Amendment is the submitting captain's reply.** It takes the
    scorecard from `DISPUTED` to `AMENDED` and simultaneously returns the match's
    `result_status` from `DISPUTED` to `REPORTED`, carrying a fresh `lines` array
    that overwrites the previous one wholesale."

    Design: Difficulty/non_linear_state_machine/match_result_dimension_cycles_while_schedule_dimension_stays_played
    """
    s = _played_match_with_a_submitted_card(api)
    assert s.scorecards["sc1"]["status"] == SCORECARD_SUBMITTED
    assert s.scorecards["sc1"]["amendment_count"] == 0
    reported = s.refresh_match("m1")
    assert reported["schedule_status"] == SCHED_PLAYED
    assert reported["result_status"] == RESULT_REPORTED

    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Line 1 second set was 6-2, not 6-0",
        disputed_line_numbers=[1],
    )
    disputed = s.refresh_match("m1")
    assert disputed["schedule_status"] == SCHED_PLAYED
    assert disputed["result_status"] == RESULT_DISPUTED

    amended = get_success_data(
        api.amend_scorecard(
            s.scorecards["sc1"]["id"],
            {"lines": _three_lines(s, [f.set_score(6, 4), f.set_score(6, 2)])},
            s.captain_headers("th"),
        )
    )
    assert amended["status"] == SCORECARD_AMENDED
    assert amended["amendment_count"] == 1
    assert amended["disputed_line_numbers"] == [1]

    back = s.refresh_match("m1")
    assert back["schedule_status"] == SCHED_PLAYED
    assert back["result_status"] == RESULT_REPORTED


def test_no_official_credit_exists_anywhere_along_the_result_cycle(api):
    """Both teams stay at zero points and no player earns a rating.

    PRD 3.6: "Both bases exclude `PENDING`, `DISPUTED` and `VOIDED` entirely."

    Design: Difficulty/non_linear_state_machine/match_result_dimension_cycles_while_schedule_dimension_stays_played
    """
    s = _played_match_with_a_submitted_card(api)
    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Line 1 second set was 6-2, not 6-0",
        disputed_line_numbers=[1],
    )
    get_success_data(
        api.amend_scorecard(
            s.scorecards["sc1"]["id"],
            {"lines": _three_lines(s, [f.set_score(6, 4), f.set_score(6, 2)])},
            s.captain_headers("th"),
        )
    )

    match = s.refresh_match("m1")
    assert match["winner_team_id"] is None
    assert match["line_results"] == []
    assert match["home_lines_won"] == 0
    assert match["away_lines_won"] == 0

    home = s.refresh_team("th")
    away = s.refresh_team("ta")
    assert home["standings_points"] == 0
    assert away["standings_points"] == 0
    assert home["matches_won"] == 0
    assert home["lines_won"] == 0

    h1 = s.refresh_player("ph1")
    assert h1["dynamic_rating"] is None
    assert h1["verified_line_count"] == 0


# ---------------------------------------------------------------------------
# Instance: scorecard_dispute_amend_cycle_stops_at_amendment_limit
# ---------------------------------------------------------------------------
def _card_at_the_amendment_ceiling(api):
    """Two full dispute/amend laps, then a third dispute leaves DISPUTED at 2."""
    s = _played_match_with_a_submitted_card(api)
    card_id = s.scorecards["sc1"]["id"]

    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Line 1 set 2 wrong",
        disputed_line_numbers=[1],
    )
    first = get_success_data(
        api.amend_scorecard(
            card_id,
            {"lines": _three_lines(s, [f.set_score(6, 4), f.set_score(6, 2)])},
            s.captain_headers("th"),
        )
    )
    assert first["amendment_count"] == 1

    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Still wrong, set 1 was 6-3",
        disputed_line_numbers=[1],
    )
    second = get_success_data(
        api.amend_scorecard(
            card_id,
            {"lines": _three_lines(s, [f.set_score(6, 3), f.set_score(6, 2)])},
            s.captain_headers("th"),
        )
    )
    assert second["amendment_count"] == 2

    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Third objection to line 1",
        disputed_line_numbers=[1],
    )
    return s, card_id


def test_the_third_amendment_is_refused_by_the_counter_not_by_the_state(api):
    """The card is legally at DISPUTED, yet amendment_count 2 bars the edge.

    PRD 3.6: "`amendment_count` increases by 1 with each amendment and is capped
    at 2: once it has reached 2 a further amendment is refused with
    `ERR_AMENDMENT_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/scorecard_dispute_amend_cycle_stops_at_amendment_limit
    """
    s, card_id = _card_at_the_amendment_ceiling(api)
    before = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    assert before["status"] == SCORECARD_DISPUTED
    assert before["amendment_count"] == 2

    response = api.amend_scorecard(
        card_id,
        {"lines": _three_lines(s, [f.set_score(6, 2), f.set_score(6, 2)])},
        s.captain_headers("th"),
    )
    validate_error(response, ERR_AMENDMENT_LIMIT_REACHED, 409)
    assert response.json()["data"]["error_id"] != ERR_SCORECARD_STATE_FORBIDS_ACTION

    after = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    assert after["status"] == SCORECARD_DISPUTED
    assert after["amendment_count"] == 2
    assert after["version"] == before["version"]


def test_the_refused_amendment_leaves_the_second_lap_lines_on_file(api):
    """Line 1 still reads 6-3 6-2 and the match stays DISPUTED at PLAYED.

    PRD 3.6: "A `DISPUTE` decision takes the scorecard from `SUBMITTED` or from
    `AMENDED` to `DISPUTED`, and takes the match's `result_status` from
    `REPORTED` to `DISPUTED`."

    Design: Difficulty/non_linear_state_machine/scorecard_dispute_amend_cycle_stops_at_amendment_limit
    """
    s, card_id = _card_at_the_amendment_ceiling(api)
    validate_error(
        api.amend_scorecard(
            card_id,
            {"lines": _three_lines(s, [f.set_score(6, 2), f.set_score(6, 2)])},
            s.captain_headers("th"),
        ),
        ERR_AMENDMENT_LIMIT_REACHED,
        409,
    )

    card = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    first_line = card["lines"][0]
    assert first_line["line_number"] == 1
    assert first_line["set_scores"] == [
        {"home_games": 6, "away_games": 3},
        {"home_games": 6, "away_games": 2},
    ]
    assert card["disputed_line_numbers"] == [1]

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_DISPUTED
    assert match["schedule_status"] == SCHED_PLAYED
    assert s.refresh_team("th")["standings_points"] == 0
    assert s.refresh_team("ta")["standings_points"] == 0


# ---------------------------------------------------------------------------
# Instance: league_reverts_rosters_locked_to_registration_open_on_withdrawal
# ---------------------------------------------------------------------------
def _locked_league_with_one_scheduled_match(api):
    s = two_team_league(api, roster_size=2, start=False)
    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    return s


def test_a_locked_league_reverts_to_registration_open_when_a_team_withdraws(api):
    """One withdrawal walks ROSTERS_LOCKED back to REGISTRATION_OPEN.

    PRD 3.4: "If the count has dropped below 2 while the league sits at
    `ROSTERS_LOCKED`, the league **reverts** to `REGISTRATION_OPEN` and every
    remaining team still at `ROSTER_LOCKED` transitions back to `REGISTERED`;
    this revert is a repair path, so it fires regardless of whether
    `registration_closes_at` has passed, and it makes the league lifecycle
    genuinely cyclic between `REGISTRATION_OPEN` and `ROSTERS_LOCKED`."

    Design: Difficulty/non_linear_state_machine/league_reverts_rosters_locked_to_registration_open_on_withdrawal
    """
    s = _locked_league_with_one_scheduled_match(api)
    assert s.refresh_league()["status"] == LEAGUE_ROSTERS_LOCKED
    assert s.refresh_team("th")["status"] == TEAM_ROSTER_LOCKED
    assert s.refresh_team("ta")["status"] == TEAM_ROSTER_LOCKED
    assert s.refresh_match("m1")["schedule_status"] == SCHED_SCHEDULED

    withdrawn = get_success_data(
        api.withdraw_team(
            s.teams["ta"]["id"],
            s.captain_headers("ta"),
            {"reason": "Two players moved out of the section"},
        )
    )
    assert withdrawn["status"] == TEAM_WITHDRAWN
    assert withdrawn["active_roster_size"] == 0

    league = s.refresh_league()
    assert league["status"] == LEAGUE_REGISTRATION_OPEN
    assert league["registered_team_count"] == 1
    assert league["noncompliant_team_count"] == 0

    home = s.refresh_team("th")
    assert home["status"] == TEAM_REGISTERED
    assert home["active_roster_size"] == 2
    assert home["roster_compliant"] is True


def test_the_revert_removes_only_the_withdrawing_teams_spots_and_cancels_the_fixture(
    api,
):
    """The surviving roster is untouched while the shared fixture is cancelled.

    PRD 3.4: "Every roster spot of the team at `PENDING`, `ACTIVE` or
    `INELIGIBLE` transitions to `REMOVED`. Every match naming the team as either
    `home_team_id` or `away_team_id` whose `schedule_status` is `UNSCHEDULED`,
    `SCHEDULED` or `CONFIRMED` transitions to `CANCELLED`, releasing whatever
    facility occupancy it held."

    Design: Difficulty/non_linear_state_machine/league_reverts_rosters_locked_to_registration_open_on_withdrawal
    """
    s = _locked_league_with_one_scheduled_match(api)
    get_success_data(
        api.withdraw_team(
            s.teams["ta"]["id"],
            s.captain_headers("ta"),
            {"reason": "Two players moved out of the section"},
        )
    )

    assert s.refresh_spot("pa1")["status"] == SPOT_REMOVED
    assert s.refresh_spot("pa2")["status"] == SPOT_REMOVED
    assert s.refresh_spot("ph1")["status"] == SPOT_ACTIVE
    assert s.refresh_spot("ph2")["status"] == SPOT_ACTIVE

    match = s.refresh_match("m1")
    assert match["schedule_status"] == SCHED_CANCELLED
    assert match["result_status"] == RESULT_PENDING

    assert match["facility_id"] == s.facility["id"]
    assert s.refresh_team("th")["matches_won"] == 0
