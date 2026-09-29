"""Formulas whose pinned step order or clamp shape changes the answer."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ERR_AUTO_GRANT_MUST_BE_GRANTED
from test_helpers.assertions import line_by_number
from test_helpers.constants import (
    APPEAL_GRANTED,
    APPEAL_UNDER_REVIEW,
    APPEAL_UP,
    CREDIT_SOURCE_TEAM_DEFAULT,
    DEFAULT_KIND_LINE_MAJORITY,
    OUTCOME_DENY,
    OUTCOME_GRANT,
    PLAYER_ACTIVE,
    RATING_APPEAL_GRANTED,
    RESULT_VERIFIED,
    SIDE_HOME,
    SPOT_ACTIVE,
    STRIKE_INELIGIBLE_LINEUP,
)
from test_helpers.fixtures import (
    played_match,
    regular_plus_playoff_season,
    six_a_side_league,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    make_player_headers,
)


# ---------------------------------------------------------------------------
# Instance: year_end_weighted_mean_rounds_each_line_before_weighting
# ---------------------------------------------------------------------------
def test_each_line_rating_is_rounded_to_three_decimals_before_it_is_weighted(api):
    """4.000 and 3.566 at weights 1.0/1.5 give 3.740, never 3.739.

    PRD 3.2: "The rounding order is fixed and not negotiable: each line rating is
    rounded to three decimals *before* it enters the mean, and the mean is
    rounded again afterwards."

    Design: Difficulty/combinatorial_formula/year_end_weighted_mean_rounds_each_line_before_weighting
    """
    s = regular_plus_playoff_season(api)
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    h1 = s.refresh_player("ph1")
    assert h1["proposed_recalc_dynamic"] == 3.740
    assert h1["proposed_recalc_dynamic"] != 3.739
    assert h1["proposed_recalc_level"] == 4.0
    assert s.refresh_player("ph2")["proposed_recalc_dynamic"] == 3.740


def test_the_pinned_rounding_order_holds_for_every_pair_on_both_rosters(api):
    """Six more weighted means, each already-rounded per line before averaging.

    PRD 2.6: "Dynamic ratings are computed to **3 decimal places using
    round-half-up**."

    Design: Difficulty/combinatorial_formula/year_end_weighted_mean_rounds_each_line_before_weighting
    """
    s = regular_plus_playoff_season(api)
    get_success_data(api.year_end_recalc(s.section["id"], SECTION_ADMIN))

    assert s.refresh_player("ph3")["proposed_recalc_dynamic"] == 3.724
    assert s.refresh_player("ph5")["proposed_recalc_dynamic"] == 3.860
    assert s.refresh_player("pa1")["proposed_recalc_dynamic"] == 4.010
    assert s.refresh_player("pa3")["proposed_recalc_dynamic"] == 4.026
    assert s.refresh_player("pa5")["proposed_recalc_dynamic"] == 3.890

    section = get_success_data(api.get_section(s.section["id"], SECTION_ADMIN))
    assert section["recalculated_player_count"] == 12


# ---------------------------------------------------------------------------
# Instance: team_default_threshold_discards_a_line_the_home_pair_actually_won
# ---------------------------------------------------------------------------
def _played_match_awaiting_a_two_default_scorecard(api):
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    lines = [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [],
            default_side=SIDE_HOME,
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [],
            default_side=SIDE_HOME,
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
    ]
    s.submit_scorecard("m1", lines)
    s.review_scorecard()
    return s


def test_two_home_line_defaults_reach_the_threshold_and_discard_the_won_line(api):
    """Line 3 was won 6-0 6-0 by home yet is credited to away as a TEAM_DEFAULT.

    PRD 3.6: "**Only the home side team-defaulted.** Every line from 1 to the
    line count - *including lines that were actually played* - is credited to the
    away side at the standard default line score, with `credit_source`
    `TEAM_DEFAULT`. The games actually played are discarded."

    Design: Difficulty/combinatorial_formula/team_default_threshold_discards_a_line_the_home_pair_actually_won
    """
    s = _played_match_awaiting_a_two_default_scorecard(api)
    match = s.refresh_match("m1")

    assert match["result_status"] == RESULT_VERIFIED
    assert match["default_side"] == SIDE_HOME
    assert match["default_kind"] == DEFAULT_KIND_LINE_MAJORITY
    assert match["winner_team_id"] == s.teams["ta"]["id"]
    assert (match["away_lines_won"], match["home_lines_won"]) == (3, 0)
    assert (match["away_sets_won"], match["home_sets_won"]) == (6, 0)
    assert (match["away_games_won"], match["home_games_won"]) == (36, 0)

    third = line_by_number(match, "line_results", 3)
    assert third["credited_to"] == s.teams["ta"]["id"]
    assert third["credit_source"] == CREDIT_SOURCE_TEAM_DEFAULT
    assert (third["away_sets"], third["home_sets"]) == (2, 0)
    assert (third["away_games"], third["home_games"]) == (12, 0)
    assert all(
        entry["credit_source"] == CREDIT_SOURCE_TEAM_DEFAULT
        for entry in match["line_results"]
    )


def test_the_discarded_line_feeds_neither_the_standings_nor_any_rating(api):
    """The away sweep banks 6 points and the home pair keeps a null rating.

    PRD 3.2: "a line credited by any mechanism other than actual play - that is,
    a `credit_source` of `LINE_DEFAULT`, `TEAM_DEFAULT` or `FORFEIT` -
    contributes nothing even when the surrounding match is `VERIFIED`."

    Design: Difficulty/combinatorial_formula/team_default_threshold_discards_a_line_the_home_pair_actually_won
    """
    s = _played_match_awaiting_a_two_default_scorecard(api)

    away = s.refresh_team("ta")
    assert away["lines_won"] == 3
    assert away["games_won"] == 36
    assert away["standings_points"] == 6
    home = s.refresh_team("th")
    assert home["lines_won"] == 0
    assert home["games_won"] == 0
    assert home["standings_points"] == 0

    h5 = s.refresh_player("ph5")
    assert h5["dynamic_rating"] is None
    assert h5["verified_line_count"] == 0
    a5 = s.refresh_player("pa5")
    assert a5["dynamic_rating"] is None
    assert a5["verified_line_count"] == 0


# ---------------------------------------------------------------------------
# Instance: auto_grant_threshold_clamped_max_min_with_strike_penalty
# ---------------------------------------------------------------------------
def _three_identical_losses_then_a_strike_and_an_appeal(api):
    """h1 is computer-rated 3.5, loses line 1 three times, then files UP to 4.0."""
    s = six_a_side_league(
        api,
        home_levels=[3.5, 4.0, 4.0, 4.0, 4.0, 4.0],
        with_committee=True,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    lines = [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(2, 6), f.set_score(2, 6)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 4), f.set_score(6, 4)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(6, 2), f.set_score(6, 2)],
        ),
    ]
    for index, day in enumerate(("15", "20", "25"), start=1):
        played_match(
            s,
            lines,
            match_key=f"m{index}",
            start_at=f"2026-08-{day}T18:00:00Z",
            end_at=f"2026-08-{day}T21:00:00Z",
            round_number=index,
            scorecard_key=f"sc{index}",
        )

    get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph1"),
                STRIKE_INELIGIBLE_LINEUP,
                reason="Fielded an unactivated substitute in round 2",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    appeal = get_success_data(
        api.create_rating_appeal(
            f.appeal_payload(
                s.player_id("ph1"),
                APPEAL_UP,
                4.0,
                reason="Three verified lines at 3.750 against 4.0 opposition",
            ),
            make_player_headers(s.player_id("ph1")),
        ),
        201,
    )
    appeal = get_success_data(api.start_appeal_review(appeal["id"], s.chair_headers()))
    return s, appeal


def test_the_strike_penalty_pulls_the_threshold_down_to_its_floor_and_deny_is_refused(
    api,
):
    """0.10*3 - 0.05*min(2,3) clamps to 0.20, below the gap of 0.250.

    PRD 3.8: "The *threshold* is built from that required count and the pinned
    strike total: take 0.10 multiplied by the required match count, subtract 0.05
    multiplied by the smaller of the pinned strike total and 3, then clamp the
    result so that it is never above 0.50 and never below 0.20."

    Design: Difficulty/combinatorial_formula/auto_grant_threshold_clamped_max_min_with_strike_penalty
    """
    s, appeal = _three_identical_losses_then_a_strike_and_an_appeal(api)

    h1 = s.refresh_player("ph1")
    assert h1["dynamic_rating"] == 3.750
    assert h1["verified_match_count"] == 3
    assert h1["strike_count"] == 2
    assert h1["status"] == PLAYER_ACTIVE

    assert appeal["rating_level_at_filing"] == 3.5
    assert appeal["dynamic_rating_at_filing"] == 3.750
    assert appeal["verified_match_count_at_filing"] == 3
    assert appeal["strike_count_at_filing"] == 2
    assert appeal["auto_grant_eligible"] is True
    assert appeal["support_vote_count"] == 0
    assert appeal["oppose_vote_count"] == 0

    validate_error(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": OUTCOME_DENY,
                "decision_note": "Rejected: the appeal is auto-grant eligible",
            },
            s.chair_headers(),
        ),
        ERR_AUTO_GRANT_MUST_BE_GRANTED,
        422,
    )
    stored = get_success_data(api.get_rating_appeal(appeal["id"], SECTION_ADMIN))
    assert stored["status"] == APPEAL_UNDER_REVIEW
    assert stored["granted_level"] is None
    assert s.refresh_player("ph1")["rating_level"] == 3.5


def test_the_auto_grant_path_grants_without_a_single_committee_vote(api):
    """No vote was ever cast, yet GRANT succeeds on auto-grant eligibility alone.

    PRD 3.8: "Also on the grant branch, either `auto_grant_eligible` must be
    true, or the committee must have delivered a quorum - `support_vote_count` at
    least 2 *and* strictly greater than `oppose_vote_count`; failing both, the
    refusal is `ERR_QUORUM_NOT_MET`."

    Design: Difficulty/combinatorial_formula/auto_grant_threshold_clamped_max_min_with_strike_penalty
    """
    s, appeal = _three_identical_losses_then_a_strike_and_an_appeal(api)

    decided = get_success_data(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": OUTCOME_GRANT,
                "decision_note": "Auto-grant path, no votes required",
            },
            s.chair_headers(),
        )
    )
    assert decided["status"] == APPEAL_GRANTED
    assert decided["granted_level"] == 4.0
    assert decided["support_vote_count"] == 0
    assert decided["oppose_vote_count"] == 0

    h1 = s.refresh_player("ph1")
    assert h1["rating_level"] == 4.0
    assert h1["rating_type"] == RATING_APPEAL_GRANTED

    spot = s.refresh_spot("ph1")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["level_at_add"] == 3.5
    assert s.refresh_league()["noncompliant_team_count"] == 0
