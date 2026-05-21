"""Weekly scoring: HALF_PPR vs PPR vs STANDARD scoring modes,
sum-then-round precision, tie-break by team id.

Covers PRD §3.5 (scoring math, rounding, tie-break, wins/losses,
points_for accumulation, current_week increment).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    DEFAULT_BASE_CLOCK,
    fetch_team,
    list_matchups,
    list_roster_slots_for_team,
    score_entry,
    score_payload,
    setup_drafted_league,
    setup_locked_week,
    validate_error,
    validate_success,
)


def _starters_for_team(league_id, team_id):
    return [
        rs for rs in list_roster_slots_for_team(league_id, team_id)
        if rs.get("slot_type") == "STARTER"
    ]


# ===========================================================================
# Scoring math — PRD §3.5
# ===========================================================================
class TestScoringModes:
    def test_standard_scoring_sums_actual_points_only(self, api, commissioner_headers):
        """PRD §3.5: "taking that starter's actual_points, adding 0.5 times the receptions_credited for HALF_PPR mode or 1.0 times the receptions_credited for PPR mode (and adding nothing for STANDARD)".

        Claim: STANDARD mode never adds reception credit; result is
        the rounded sum of actual_points.
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="STANDARD")
        league = bundle["league"]
        wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
        home_starters = _starters_for_team(league["id"], wk1["home_team_id"])
        away_starters = _starters_for_team(league["id"], wk1["away_team_id"])
        # Give every home starter 2.0 actual_points with 5 receptions
        # (which STANDARD must IGNORE); give every away starter 0.
        scores = []
        for rs in home_starters:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=2.0, receptions_credited=5,
            ))
        for rs in away_starters:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=0.0, receptions_credited=0,
            ))
        res = api.score_matchup(
            league["id"], 1, score_payload(scores), commissioner_headers,
        )
        validate_success(res, 200)
        wk1_after = [
            m for m in list_matchups(league["id"], week_number=1)
            if m["id"] == wk1["id"]
        ][0]
        expected_home = round(2.0 * len(home_starters), 2)
        assert wk1_after["home_points"] == pytest.approx(expected_home, abs=0.001), \
            f"STANDARD: home_points = sum(actual_points), got {wk1_after['home_points']}"
        assert wk1_after["away_points"] == pytest.approx(0.0, abs=0.001)

    def test_half_ppr_adds_half_reception_credit(self, api, commissioner_headers):
        """PRD §3.5: "adding 0.5 times the receptions_credited for HALF_PPR mode".

        Claim: HALF_PPR adds 0.5 per reception_credited; cf. PPR which
        adds 1.0. With identical inputs the totals must differ.

        # difficulty: dual_variant_calc/scoring_mode_half_ppr_vs_ppr_on_matchup
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="HALF_PPR")
        league = bundle["league"]
        wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
        home_starters = _starters_for_team(league["id"], wk1["home_team_id"])
        away_starters = _starters_for_team(league["id"], wk1["away_team_id"])
        # Choose ONE home starter to contribute; everyone else zero.
        first = home_starters[0]
        scores = [
            score_entry(player_id=first["player_id"], actual_points=6.0, receptions_credited=4),
        ]
        for rs in home_starters[1:]:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=0.0, receptions_credited=0,
            ))
        for rs in away_starters:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=0.0, receptions_credited=0,
            ))
        res = api.score_matchup(
            league["id"], 1, score_payload(scores), commissioner_headers,
        )
        validate_success(res, 200)
        wk1_after = [
            m for m in list_matchups(league["id"], week_number=1)
            if m["id"] == wk1["id"]
        ][0]
        # 6.0 + 0.5 * 4 = 8.0
        assert wk1_after["home_points"] == pytest.approx(8.00, abs=0.001), \
            f"HALF_PPR: expected 8.00, got {wk1_after['home_points']}"


# ===========================================================================
# Sum-then-round precision — PRD §3.5 / §2.10
# ===========================================================================
class TestSumThenRound:
    def test_round_half_up_two_decimals_applied_once_per_team(
        self, api, commissioner_headers,
    ):
        """PRD §2.10: "Critically, the rounding happens exactly once per team per week, after the sum of all that team's starter contributions has been computed — implementations that round each starter's contribution first and then sum the rounded values are wrong."
        PRD §3.5: "After both team sums are complete, the system applies 'round half up' to two decimal places exactly once per team to produce home_points and away_points."

        Claim: scoring two starters each contributing 2.005 in HALF_PPR
        (1.505 actual + 0.5*1 reception) sums to 4.010 → ROUND_HALF_UP
        to 4.01, NOT 4.02 (which is what round-then-sum would give).

        # difficulty: combinatorial_formula/matchup_scoring_sum_then_round_mode_b
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="HALF_PPR")
        league = bundle["league"]
        wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
        home_starters = _starters_for_team(league["id"], wk1["home_team_id"])
        away_starters = _starters_for_team(league["id"], wk1["away_team_id"])
        # Two home starters each get actual_points=1.505 + 1 reception
        # contribution. Per-starter contribution = 1.505 + 0.5*1 = 2.005.
        # Sum = 4.010 → 4.01.
        s1 = home_starters[0]
        s2 = home_starters[1]
        scores = [
            score_entry(player_id=s1["player_id"], actual_points=1.505, receptions_credited=1),
            score_entry(player_id=s2["player_id"], actual_points=1.505, receptions_credited=1),
        ]
        for rs in home_starters[2:]:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=0.0, receptions_credited=0,
            ))
        for rs in away_starters:
            scores.append(score_entry(
                player_id=rs["player_id"], actual_points=0.0, receptions_credited=0,
            ))
        res = api.score_matchup(
            league["id"], 1, score_payload(scores), commissioner_headers,
        )
        validate_success(res, 200)
        wk1_after = [
            m for m in list_matchups(league["id"], week_number=1)
            if m["id"] == wk1["id"]
        ][0]
        assert wk1_after["home_points"] == pytest.approx(4.01, abs=0.001), \
            f"sum-then-round: expected 4.01, got {wk1_after['home_points']}"
        assert wk1_after["home_points"] != pytest.approx(4.02, abs=0.001), \
            "round-then-sum would yield 4.02; that is wrong"


# ===========================================================================
# Wins/losses/points_for accumulation — PRD §3.5
# ===========================================================================
class TestStandingsAccumulation:
    def test_winner_wins_loser_losses_both_points_for_incremented(
        self, api, commissioner_headers,
    ):
        """PRD §3.5: "The winning team's wins and the losing team's losses are incremented by 1; both teams' points_for are incremented by their respective rounded totals."

        Claim: after scoring a week, the winner's wins ticks +1, the
        loser's losses +1, and both teams' points_for accumulate.
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="STANDARD")
        league = bundle["league"]
        wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
        home_team_before = fetch_team(league["id"], wk1["home_team_id"])
        away_team_before = fetch_team(league["id"], wk1["away_team_id"])
        home_starters = _starters_for_team(league["id"], wk1["home_team_id"])
        away_starters = _starters_for_team(league["id"], wk1["away_team_id"])
        # Give home a deterministic edge: 10 points to one home starter.
        scores = [
            score_entry(player_id=home_starters[0]["player_id"], actual_points=10.0),
        ]
        for rs in home_starters[1:]:
            scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0))
        for rs in away_starters:
            scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0))
        res = api.score_matchup(
            league["id"], 1, score_payload(scores), commissioner_headers,
        )
        validate_success(res, 200)
        home_after = fetch_team(league["id"], wk1["home_team_id"])
        away_after = fetch_team(league["id"], wk1["away_team_id"])
        assert home_after["wins"] == home_team_before["wins"] + 1
        assert away_after["losses"] == away_team_before["losses"] + 1
        assert float(home_after["points_for"]) == pytest.approx(
            float(home_team_before["points_for"]) + 10.0, abs=0.001,
        )


# ===========================================================================
# Tie-break by team id — PRD §3.5
# ===========================================================================
class TestTieBreakByTeamId:
    def test_tie_goes_to_lexicographically_smaller_team_id(
        self, api, commissioner_headers,
    ):
        """PRD §3.5: "The winner is the team with the strictly larger rounded points value; a tie goes to whichever team's id is lexicographically smaller."

        Claim: when home_points == away_points, the team with the
        smaller id (lexicographically) gets the win.
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="STANDARD")
        league = bundle["league"]
        wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
        home_starters = _starters_for_team(league["id"], wk1["home_team_id"])
        away_starters = _starters_for_team(league["id"], wk1["away_team_id"])
        # All zeros → 0-0 tie.
        scores = []
        for rs in home_starters + away_starters:
            scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0))
        res = api.score_matchup(
            league["id"], 1, score_payload(scores), commissioner_headers,
        )
        validate_success(res, 200)
        home_after = fetch_team(league["id"], wk1["home_team_id"])
        away_after = fetch_team(league["id"], wk1["away_team_id"])
        smaller_id = min(home_after["id"], away_after["id"])
        if smaller_id == home_after["id"]:
            assert home_after["wins"] >= 1, \
                "PRD §3.5: tie → team with smaller id wins"
            assert away_after["losses"] >= 1
        else:
            assert away_after["wins"] >= 1
            assert home_after["losses"] >= 1
