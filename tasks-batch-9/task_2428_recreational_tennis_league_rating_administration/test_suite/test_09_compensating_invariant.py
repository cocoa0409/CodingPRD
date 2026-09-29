"""Conserved quantities restored by compensating actions."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.assertions import assert_league_ledger_invariants, standings_by_team
from test_helpers.constants import (
    CREDIT_SOURCE_FORFEIT,
    GRIEVANCE_SCORE_FALSIFICATION,
    GRIEVANCE_UPHELD,
    OUTCOME_UPHOLD,
    PLAYER_ACTIVE,
    PLAYER_STRIKE_SUSPENDED,
    REMEDY_MATCH_FORFEIT,
    RESULT_REPORTED,
    RESULT_VERIFIED,
    RESULT_VOIDED,
    REVIEW_DISPUTE,
    SCHED_DEFAULTED,
    SCORECARD_AMENDED,
    SCORECARD_DISPUTED,
    SCORECARD_SUBMITTED,
    SCORECARD_VOIDED,
    SIDE_AWAY,
    SIDE_HOME,
    SPOT_ACTIVE,
    SPOT_INELIGIBLE,
    STRIKE_ACTIVE,
    STRIKE_INELIGIBLE_LINEUP,
    STRIKE_NO_SHOW_DEFAULT,
    STRIKE_RESCINDED,
    SUBJECT_GRIEVANCE,
    VOTE_SUPPORT,
)
from test_helpers.fixtures import played_match, standard_three_lines, two_team_league
from test_helpers.test_users import LEAGUE_COORDINATOR, SECTION_ADMIN


# ---------------------------------------------------------------------------
# Instance: strike_rescission_restores_the_weighted_ledger_and_only_its_own_spots
# ---------------------------------------------------------------------------
def _player_with_one_weight_one_strike(api):
    s = two_team_league(
        api,
        roster_size=2,
        with_committee=True,
        section_kwargs={
            "min_matches_for_playoff_eligibility": 1,
            "strike_limit": 3,
            "disqualification_strike_limit": 6,
        },
    )
    first = get_success_data(
        api.create_strike(
            f.strike_payload(
                s.player_id("ph2"),
                STRIKE_NO_SHOW_DEFAULT,
                reason="Missed a rescheduled fixture",
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    return s, first


def test_second_strike_reaching_the_limit_suspends_and_marks_only_its_own_spot(api):
    """1 + 2 == strike_limit 3 suspends h2; a2's untouched ledger stays at 0.

    PRD 3.7: "With the default `strike_limit` of 3, a `NO_SHOW_DEFAULT` weighing
    1 landing on top of an `INELIGIBLE_LINEUP` weighing 2 suspends the player at
    exactly 3 - the threshold is reached, not merely passed."

    Design: Difficulty/compensating_invariant/strike_rescission_restores_the_weighted_ledger_and_only_its_own_spots
    """
    s, first = _player_with_one_weight_one_strike(api)

    second = get_success_data(
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
    assert first["weight"] == 1
    assert second["weight"] == 2

    player = s.refresh_player("ph2")
    assert player["strike_count"] == 3
    assert player["status"] == PLAYER_STRIKE_SUSPENDED
    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_INELIGIBLE
    assert spot["source_strike_id"] == second["id"]
    assert s.refresh_player("pa2")["strike_count"] == 0
    assert s.refresh_spot("pa2")["status"] == SPOT_ACTIVE


def test_rescinding_the_weight_two_strike_restores_the_ledger_to_exactly_one(api):
    """Rescission subtracts the rescinded weight, not a flat 1.

    PRD 3.7: "A player's `strike_count` is not a tally of strike rows; it is the
    **sum of the `weight` of every strike charged to that player whose `status`
    is `ACTIVE`**."

    Design: Difficulty/compensating_invariant/strike_rescission_restores_the_weighted_ledger_and_only_its_own_spots
    """
    s, first = _player_with_one_weight_one_strike(api)
    second = get_success_data(
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

    rescinded = get_success_data(
        api.rescind_strike(
            second["id"],
            {"rescinded_reason": "Roster paperwork was filed on time after all"},
            s.chair_headers(),
        )
    )
    assert rescinded["status"] == STRIKE_RESCINDED
    assert rescinded["weight"] == 2
    assert rescinded["rescinded_reason"] == "Roster paperwork was filed on time after all"

    still_active = get_success_data(api.get_strike(first["id"], SECTION_ADMIN))
    assert still_active["status"] == STRIKE_ACTIVE
    assert still_active["weight"] == 1

    player = s.refresh_player("ph2")
    assert player["strike_count"] == 1
    assert player["status"] == PLAYER_ACTIVE

    spot = s.refresh_spot("ph2")
    assert spot["status"] == SPOT_ACTIVE
    assert spot["ineligible_reason"] is None
    assert spot["source_strike_id"] is None

    team = s.refresh_team("th")
    assert team["active_roster_size"] == 2
    assert team["roster_compliant"] is True
    assert s.refresh_league()["noncompliant_team_count"] == 0

    rows, _meta = validate_paginated(api.list_strikes(SECTION_ADMIN, {"limit": 100}))
    active_for_h2 = [
        row
        for row in rows
        if row["player_id"] == s.player_id("ph2") and row["status"] == STRIKE_ACTIVE
    ]
    assert len(active_for_h2) == 1


# ---------------------------------------------------------------------------
# Instance: forfeit_void_reversal_plus_recredit_keeps_all_four_ledger_invariants
# ---------------------------------------------------------------------------
def _verified_match_plus_away_default_and_upheld_grievance(api):
    s = two_team_league(
        api,
        roster_size=6,
        with_committee=True,
        away_levels=[4.0, 3.5, 4.0, 3.5, 4.0, 3.5],
    )
    played_match(s, standard_three_lines(s), match_key="m1")

    s.create_match("m4", "th", "ta", round_number=2)
    s.schedule_match("m4", "2026-08-16T18:00:00Z", 3)
    s.set_clock("2026-08-16T18:00:00Z")
    s.default_match("m4", SIDE_AWAY, "NO_SHOW")

    grievance = get_success_data(
        api.create_grievance(
            f.grievance_payload(
                s.league["id"],
                s.teams["th"]["id"],
                GRIEVANCE_SCORE_FALSIFICATION,
                subject_match_id=s.matches["m1"]["id"],
                statement=(
                    "The line 2 second set was recorded as 6-3 for the home pair "
                    "but was won 6-3 by us"
                ),
            ),
            s.captain_headers("ta"),
        ),
        201,
    )
    get_success_data(api.start_grievance_review(grievance["id"], s.chair_headers()))
    for member in ("pc1", "pc2"):
        get_success_data(
            api.create_committee_vote(
                f.vote_payload(grievance["id"], VOTE_SUPPORT, SUBJECT_GRIEVANCE),
                s.member_headers(member),
            ),
            201,
        )
    return s, grievance


def test_match_forfeit_voids_the_match_and_recredits_three_lines_at_six_love(api):
    """The remedy reverses the played credit and grants a fresh forfeit credit.

    PRD 3.8: "Then a forfeit credit is applied to the team that is *not* the
    accused team: exactly `lines_per_match` lines, each at two sets six games to
    love and six to love"

    Design: Difficulty/compensating_invariant/forfeit_void_reversal_plus_recredit_keeps_all_four_ledger_invariants
    """
    s, grievance = _verified_match_plus_away_default_and_upheld_grievance(api)

    decided = get_success_data(
        api.decide_grievance(
            grievance["id"],
            {
                "outcome": OUTCOME_UPHOLD,
                "remedy": REMEDY_MATCH_FORFEIT,
                "decision_note": "Scorecard falsified on line 2",
            },
            s.chair_headers(),
        )
    )
    assert decided["status"] == GRIEVANCE_UPHELD
    assert decided["remedy"] == REMEDY_MATCH_FORFEIT

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_VOIDED
    assert match["winner_team_id"] == s.teams["ta"]["id"]
    assert match["default_side"] == SIDE_HOME
    assert match["away_lines_won"] == 3
    assert match["home_lines_won"] == 0
    assert match["away_sets_won"] == 6
    assert match["away_games_won"] == 36
    assert len(match["line_results"]) == 3
    assert all(
        entry["credit_source"] == CREDIT_SOURCE_FORFEIT
        for entry in match["line_results"]
    )
    card = get_success_data(
        api.get_scorecard(s.scorecards["sc1"]["id"], SECTION_ADMIN)
    )
    assert card["status"] == SCORECARD_VOIDED


def test_match_forfeit_keeps_all_four_league_ledger_invariants(api):
    """Team H falls 11 -> 6 and Team A rises 1 -> 3 with the ledger still exact.

    PRD 3.8: "each affected team recomputes `playoff_eligible_roster_size` and
    `standings_points`; and the four ledger invariants of §2.11 must hold after
    the reversal plus the forfeit credit."

    Design: Difficulty/compensating_invariant/forfeit_void_reversal_plus_recredit_keeps_all_four_ledger_invariants
    """
    s, grievance = _verified_match_plus_away_default_and_upheld_grievance(api)
    get_success_data(
        api.decide_grievance(
            grievance["id"],
            {
                "outcome": OUTCOME_UPHOLD,
                "remedy": REMEDY_MATCH_FORFEIT,
                "decision_note": "Scorecard falsified on line 2",
            },
            s.chair_headers(),
        )
    )

    home = s.refresh_team("th")
    away = s.refresh_team("ta")
    assert (home["matches_won"], home["matches_lost"]) == (1, 0)
    assert (home["lines_won"], home["lines_lost"]) == (3, 3)
    assert (home["sets_won"], home["sets_lost"]) == (6, 6)
    assert (home["games_won"], home["games_lost"]) == (36, 36)
    assert home["standings_points"] == 6
    assert (away["matches_won"], away["matches_lost"]) == (0, 1)
    assert (away["lines_won"], away["lines_lost"]) == (3, 3)
    assert (away["sets_won"], away["sets_lost"]) == (6, 6)
    assert (away["games_won"], away["games_lost"]) == (36, 36)
    assert away["standings_points"] == 3

    # Exactly one decided match remains: the away-side default M4.
    assert_league_ledger_invariants(home, away, decided_match_count=1)


def test_match_forfeit_leaves_no_rating_credit_and_keeps_the_default_strike(api):
    """FORFEIT and TEAM_DEFAULT credits never feed a rating.

    PRD 3.2: "a line credited by any mechanism other than actual play - that is,
    a `credit_source` of `LINE_DEFAULT`, `TEAM_DEFAULT` or `FORFEIT` -
    contributes nothing even when the surrounding match is `VERIFIED`."

    Design: Difficulty/compensating_invariant/forfeit_void_reversal_plus_recredit_keeps_all_four_ledger_invariants
    """
    s, grievance = _verified_match_plus_away_default_and_upheld_grievance(api)
    get_success_data(
        api.decide_grievance(
            grievance["id"],
            {
                "outcome": OUTCOME_UPHOLD,
                "remedy": REMEDY_MATCH_FORFEIT,
                "decision_note": "Scorecard falsified on line 2",
            },
            s.chair_headers(),
        )
    )

    h1 = s.refresh_player("ph1")
    assert h1["dynamic_rating"] is None
    assert h1["verified_line_count"] == 0
    assert s.refresh_player("ph5")["dynamic_rating"] is None
    a1 = s.refresh_player("pa1")
    assert a1["dynamic_rating"] is None
    assert a1["strike_count"] == 1
    assert a1["status"] == PLAYER_ACTIVE

    m4 = s.refresh_match("m4")
    assert m4["result_status"] == RESULT_VERIFIED
    assert m4["schedule_status"] == SCHED_DEFAULTED


# ---------------------------------------------------------------------------
# Instance: dispute_and_identical_amend_conserve_the_provisional_credit_exactly
# ---------------------------------------------------------------------------
def _reported_match_awaiting_review(api):
    s = two_team_league(api, roster_size=6)
    lines = standard_three_lines(s)
    played_match(s, lines, match_key="m1", verify=False)
    return s, lines


def _provisional_points(s):
    by_team = standings_by_team(s.api, s.league["id"], SECTION_ADMIN, "provisional")
    return (
        by_team[s.teams["th"]["id"]]["standings_points"],
        by_team[s.teams["ta"]["id"]]["standings_points"],
    )


def test_dispute_withdraws_the_whole_provisional_credit(api):
    """A REPORTED card credits 5/1 provisionally; DISPUTED collapses it to 0/0.

    PRD 3.6: "The standings consequence is immediate: a disputed match is
    excluded from *both* standings bases, so whatever provisional contribution
    the submission created is withdrawn."

    Design: Difficulty/compensating_invariant/dispute_and_identical_amend_conserve_the_provisional_credit_exactly
    """
    s, _lines = _reported_match_awaiting_review(api)
    assert s.scorecards["sc1"]["status"] == SCORECARD_SUBMITTED
    assert s.refresh_match("m1")["result_status"] == RESULT_REPORTED
    assert _provisional_points(s) == (5, 1)

    card = s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Line 2 second set is wrong",
        disputed_line_numbers=[2],
    )
    assert card["status"] == SCORECARD_DISPUTED
    assert _provisional_points(s) == (0, 0)
    home = s.refresh_team("th")
    away = s.refresh_team("ta")
    assert home["standings_points"] == 0
    assert away["standings_points"] == 0


def test_identical_amendment_restores_the_provisional_credit_exactly(api):
    """Re-stating the same line scores returns the provisional basis to 5/1.

    PRD 3.6: "Every amendment recomputes the provisional standings of both
    teams, and the scorecard's `version` and the match's `version` each increase
    by 1."

    Design: Difficulty/compensating_invariant/dispute_and_identical_amend_conserve_the_provisional_credit_exactly
    """
    s, lines = _reported_match_awaiting_review(api)
    s.review_scorecard(
        decision=REVIEW_DISPUTE,
        dispute_reason="Line 2 second set is wrong",
        disputed_line_numbers=[2],
    )

    amended = get_success_data(
        api.amend_scorecard(
            s.scorecards["sc1"]["id"], {"lines": lines}, s.captain_headers("th")
        )
    )
    assert amended["status"] == SCORECARD_AMENDED
    assert amended["amendment_count"] == 1
    assert s.refresh_match("m1")["result_status"] == RESULT_REPORTED
    assert _provisional_points(s) == (5, 1)
    assert s.refresh_team("th")["standings_points"] == 0
    assert s.refresh_team("ta")["standings_points"] == 0
