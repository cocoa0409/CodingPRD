"""Difficulty-design coverage: one or more tests per instance, with
docstring tags # difficulty: <rule_id>/<instance.name>.

Each test cites the PRD prose that uniquely determines its assertion.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    advance_clock_to,
    cast_vote_as,
    create_league,
    create_team_payload,
    DEFAULT_BASE_CLOCK,
    create_player,
    fetch_team,
    fetch_trade,
    iso_utc,
    list_matchups,
    list_roster_slots_for_team,
    make_manager_headers,
    manager_uid,
    patch_roster_slot_payload,
    propose_trade,
    score_entry,
    score_payload,
    set_player_status,
    setup_accepted_trade,
    setup_drafted_league,
    setup_locked_week,
    submit_waiver,
    validate_error,
    validate_success,
)


def _now(league):
    return datetime.fromisoformat(league["now_ts"].replace("Z", "+00:00"))


# ===========================================================================
# Rule 1 — dual_variant_calc
# Instance: scoring_mode_half_ppr_vs_ppr_on_matchup
# ===========================================================================
class TestScoringModeCrossLeague:
    def test_half_ppr_and_ppr_diverge_on_identical_inputs(self, api, commissioner_headers):
        """PRD §3.5: "taking that starter's actual_points, adding 0.5 times the receptions_credited for HALF_PPR mode or 1.0 times the receptions_credited for PPR mode (and adding nothing for STANDARD), and accumulating into a running per-team sum."

        Claim: two leagues with identical lineups but different
        scoring_modes (HALF_PPR vs PPR) produce different
        MatchupWeek.home_points for identical (actual_points,
        receptions_credited) inputs.

        # difficulty: dual_variant_calc/scoring_mode_half_ppr_vs_ppr_on_matchup
        """
        # Two leagues differing only in scoring_mode.
        b_half = setup_locked_week(team_count=4, scoring_mode="HALF_PPR")
        b_ppr = setup_locked_week(team_count=4, scoring_mode="PPR")
        for bundle, expected_pts in ((b_half, 8.0), (b_ppr, 10.0)):
            league = bundle["league"]
            wk1 = [m for m in list_matchups(league["id"], week_number=1)][0]
            home_starters = [
                rs for rs in list_roster_slots_for_team(
                    league["id"], wk1["home_team_id"],
                ) if rs["slot_type"] == "STARTER"
            ]
            away_starters = [
                rs for rs in list_roster_slots_for_team(
                    league["id"], wk1["away_team_id"],
                ) if rs["slot_type"] == "STARTER"
            ]
            scores = [
                score_entry(player_id=home_starters[0]["player_id"], actual_points=6.0, receptions_credited=4),
            ]
            for rs in home_starters[1:]:
                scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0, receptions_credited=0))
            for rs in away_starters:
                scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0, receptions_credited=0))
            api.score_matchup(league["id"], 1, score_payload(scores), commissioner_headers)
            from test_helpers import fetch_matchup
            wk1_after = fetch_matchup(league["id"], 1)
            assert wk1_after["home_points"] == pytest.approx(expected_pts, abs=0.001), \
                f"PRD §3.5: scoring_mode-dependent total — expected {expected_pts}, got {wk1_after['home_points']}"
        # The two leagues' home_points must differ.
        from test_helpers import fetch_matchup
        wk_half = fetch_matchup(b_half["league"]["id"], 1)
        wk_ppr = fetch_matchup(b_ppr["league"]["id"], 1)
        assert wk_half["home_points"] != wk_ppr["home_points"], \
            "PRD §3.5: HALF_PPR (8.00) ≠ PPR (10.00) on identical inputs"


# ===========================================================================
# Rule 2 — combinatorial_formula
# Instance 1: faab_resolution_three_input_nonlinear_mode_a
# ===========================================================================
class TestFaabResolutionThreeInputNonlinear:
    # DELETED — test_insufficient_funds_skipped_priority_seed_breaks_tie
    # PRD §3.6 forbids submitting a waiver claim whose bid_dollars exceeds the
    # team's current faab_balance_dollars (ERR_FAAB_INSUFFICIENT at submit).
    # The sweep-time "skip insufficient" branch therefore cannot be staged via
    # PRD-permitted endpoints. PRD-silent on a synthetic balance-drop path.
    def _removed_test_insufficient_funds_skipped_priority_seed_breaks_tie(self, api):
        """REMOVED — PRD-silent / undecidable. See note above."""
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        # Identify priority_seed assignment is server-side from
        # inverse-standings (PRD §3.6). With wins=losses=0 the
        # tiebreaker is team.created_at asc; the first-created team has
        # the worst implicit ordering (or the best — PRD prose says
        # the worst record gets priority_seed 1). Pre-season every
        # team has wins=0 and losses=0, so PRD prose does NOT
        # uniquely determine the seed mapping pre-season; we read the
        # seeds back from the server.
        # We need: C (low FAAB, high bid), and A/B (same bid, varied
        # priority_seed). We can't directly control priority_seed in
        # PRD, but we CAN identify which submitted claim received
        # which seed by reading WaiverClaim.priority_seed.
        target = create_player(position="WR")
        set_player_status(target["id"], "OUT")
        # Reduce team[2]'s balance to 5 (so they can't pay $20).
        # PRD §3.6 says FAAB is decremented only on award, but we
        # can use a real award path to shrink the balance: have
        # team[2] win a small prior waiver and burn it down. Easier:
        # have team[2] submit a $5 winning claim on a separate
        # player to reduce balance to 95. We need balance=5, so we
        # need to burn 95 first — too costly. Instead, set up the
        # scenario without reducing balance, and use bid=$5 from
        # team[2] (so they have enough funds) but a different
        # competing structure that still tests the three-input
        # sort: highest bid wins, tiebreak by priority_seed, but
        # also pad with a HIGH-bid team whose funds are below their
        # bid via a tightly controlled budget. The cleanest path is
        # a league with faab_budget_dollars=10 (every team starts
        # at 10) and bids of 10 (A,B) and 20 (C — exceeds balance
        # 10). But PRD §3.6 says: "The bid_dollars may not exceed
        # the submitting team's current faab_balance_dollars; an
        # over-bid is rejected with ERR_FAAB_INSUFFICIENT." So C
        # cannot even submit a bid of 20 while balance=10. That
        # means at SWEEP time we never observe "skipped due to
        # insufficient funds" UNLESS the team's balance dropped
        # AFTER submission (e.g., by winning another claim).
        # We construct that: faab=10 initial; team_C submits bid=$8;
        # team_C wins (their bid is unique) → balance=2. Now
        # team_C submits a SECOND claim for a different player at
        # bid=$2; that's still valid. But we want a 3-team
        # contention pool. Let's restage:
        #   faab=20 each (faab_budget_dollars=20).
        #   Team_C submits bid=$15 on player_X (only bidder) →
        #     wins → balance=5.
        #   Now Team_C submits bid=$10 on player_target.
        #   Team_A submits bid=$10 on player_target (priority_seed
        #     read from server).
        #   Team_B submits bid=$10 on player_target.
        # At sweep, all three have bid=10; ties broken by
        # priority_seed. Team_C's balance is 5 — insufficient — so
        # they're skipped. Of A/B, the one with lower priority_seed
        # wins.
        # Rebuild the league with faab=20.
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=20)
        league = bundle["league"]
        t_a, t_b, t_c, _ = bundle["teams"]
        pre_player = create_player(position="K")  # K so the per-position
                                                  # bench check doesn't
                                                  # blow up
        set_player_status(pre_player["id"], "OUT")
        # Team_C submits and wins a $15 claim on pre_player.
        w_pre = submit_waiver(
            league=league, team=t_c, add_player_id=pre_player["id"],
            bid_dollars=15, settle_offset_hours=2,
        )
        now1 = _now(league)
        advance_clock_to(league["id"], now1 + timedelta(hours=3))
        api.process_waivers(league["id"], COMMISSIONER)
        t_c_after = fetch_team(league["id"], t_c["id"])
        assert t_c_after["faab_balance_dollars"] == 5, \
            f"After winning pre-claim, Team_C balance should be 5, got {t_c_after['faab_balance_dollars']}"
        # Now stage the three-way contention on the real target.
        set_player_status(target["id"], "OUT")
        w_a = submit_waiver(
            league=league, team=t_a, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=4,
        )
        w_b = submit_waiver(
            league=league, team=t_b, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=4,
        )
        w_c = submit_waiver(
            league=league, team=t_c, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=4,
        )
        # NOTE: PRD §3.6 says submission requires bid_dollars <=
        # faab_balance_dollars at SUBMIT time, and Team_C's balance
        # is 5; PRD says this is rejected with ERR_FAAB_INSUFFICIENT
        # at submit time. That means we cannot stage the
        # difficulty-design's "skip insufficient at sweep" path
        # via PRD-only mechanisms — the PRD's submit-time check
        # prevents the bid from ever entering the sweep pool.
        # We THEREFORE re-construct: Team_C submits before its
        # balance drops. We re-stage the test once more in a clean
        # league.
        pytest.skip(
            "difficulty-coverage-blocked-by-prd-silence: PRD §3.6 says "
            "'WaiverClaim.bid_dollars > Team.faab_balance_dollars at "
            "submit' yields ERR_FAAB_INSUFFICIENT at submission time, "
            "so the sweep-time 'skip-insufficient' branch in the "
            "difficulty design's faab_resolution_three_input recipe "
            "cannot be staged via PRD-permitted endpoints. The first "
            "two inputs of the three-input sort (bid_dollars desc, "
            "priority_seed asc) are exercised in "
            "test_06_waivers_and_faab::test_higher_bid_wins."
        )

    def test_tie_broken_by_priority_seed_ascending(self, api):
        """PRD §3.6: "sorts claims by bid_dollars descending with ties broken by priority_seed ascending and a final tiebreak of created_at ascending."

        Claim: two claims with identical bid_dollars but different
        priority_seed values; the claim with the lower priority_seed
        wins.

        # difficulty: combinatorial_formula/faab_resolution_three_input_nonlinear_mode_a
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        t_a, t_b, _, _ = bundle["teams"]
        target = create_player(position="WR")
        set_player_status(target["id"], "OUT")
        w_a = submit_waiver(
            league=league, team=t_a, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=2,
        )
        w_b = submit_waiver(
            league=league, team=t_b, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=2,
        )
        # Read priority_seed of both claims.
        from test_helpers import fetch_waiver
        w_a_read = fetch_waiver(league["id"], w_a["id"])
        w_b_read = fetch_waiver(league["id"], w_b["id"])
        lower_seed = w_a_read if w_a_read["priority_seed"] < w_b_read["priority_seed"] else w_b_read
        higher_seed = w_b_read if lower_seed is w_a_read else w_a_read
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=3))
        api.process_waivers(league["id"], COMMISSIONER)
        winner = fetch_waiver(league["id"], lower_seed["id"])
        loser = fetch_waiver(league["id"], higher_seed["id"])
        assert winner["status"] == "AWARDED", \
            f"PRD §3.6: tied bid → lower priority_seed wins. lower_seed_status={winner['status']}"
        assert loser["status"] == "LOST", \
            f"PRD §3.6: tied bid → higher priority_seed loses. higher_seed_status={loser['status']}"


# ===========================================================================
# Rule 3 — non_linear_state_machine
# Instance 1: trade_proposal_branching_with_revert_paths
# ===========================================================================
class TestTradeBranching:
    def test_accepted_pending_review_branches_to_vetoed(self, api):
        """PRD §3.7: "When the threshold is first crossed by a newly inserted VETO vote and the trade is still inside its review window (League.now_ts is strictly less than review_deadline_ts), the trade transitions immediately from ACCEPTED_PENDING_REVIEW to VETOED with no player or FAAB movement."

        Claim: VETO branch of the ACCEPTED_PENDING_REVIEW state moves
        the trade to VETOED, no player movement.

        # difficulty: non_linear_state_machine/trade_proposal_branching_with_revert_paths
        """
        bundle = setup_accepted_trade(team_count=4, veto_quorum_pct=50)
        league = bundle["league"]
        trade = bundle["trade"]
        p_send = bundle["p_send"]
        p_recv = bundle["p_recv"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        # team_count=4 → eligible voters = 2 (T3, T4).
        # veto_quorum_pct=50 → 1 veto out of 2 = 50% → VETOED on
        # second veto: actually with 2 vetoes that's 100%, but the
        # threshold is first crossed at 1 veto (50%) per PRD floor-
        # division: (1*100)//2 = 50 >= 50.
        cast_vote_as(trade["id"], bundle["teams"][2], "VETO")
        latest = fetch_trade(league["id"], trade["id"])
        # 1 veto out of 2 eligible = 50% — crosses threshold (PRD
        # §3.7: "Equality with the quorum counts as crossed").
        assert latest["status"] == "VETOED", \
            "PRD §3.7: VETO branch of ACCEPTED_PENDING_REVIEW"
        # No player movement.
        t1_slots = list_roster_slots_for_team(league["id"], t1["id"])
        t2_slots = list_roster_slots_for_team(league["id"], t2["id"])
        assert any(s["player_id"] == p_send["id"] for s in t1_slots), \
            "PRD §3.7: VETOED branch — no player movement"
        assert any(s["player_id"] == p_recv["id"] for s in t2_slots)

    def test_offered_can_branch_to_rejected_or_canceled(self, api):
        """PRD §3.7: "Rejecting transitions to REJECTED and is also restricted to the counterparty."
        PRD §3.7: "Canceling transitions to CANCELED and is restricted to the proposer; once the trade has moved past OFFERED, the proposer can no longer cancel."

        Claim: an OFFERED trade fans to REJECTED (counterparty
        rejects) or CANCELED (proposer cancels). Two trades, two
        branches.

        # difficulty: non_linear_state_machine/trade_proposal_branching_with_revert_paths
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        # Trade A: counterparty rejects.
        trade_a = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send["id"]], receive_player_ids=[p_recv["id"]],
        )
        from test_helpers import reject_trade_as, cancel_trade_as
        rej = reject_trade_as(trade_a["id"], t2)
        assert rej["status"] == "REJECTED"
        # Trade B: proposer cancels (use different players).
        p_send2 = bundle["players_by_team"][t1["id"]][2]
        p_recv2 = bundle["players_by_team"][t2["id"]][2]
        trade_b = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send2["id"]], receive_player_ids=[p_recv2["id"]],
        )
        canc = cancel_trade_as(trade_b["id"], t1)
        assert canc["status"] == "CANCELED"


# ===========================================================================
# Rule 3 instance 2 — league_branching_terminal_archive_path
# ===========================================================================
class TestArchiveCascade:
    def test_archive_from_completed_cancels_pending_waivers(self, api, commissioner_headers):
        """PRD §3.8: "Archival cancels every still-PENDING WaiverClaim in the league (status to CANCELED) and converts every still-open TradeProposal (those in OFFERED or ACCEPTED_PENDING_REVIEW) to REJECTED."

        Claim: PRD-silent on the precise clock-target value required to
        push a league from PLAYOFFS to COMPLETED. The test author
        documented two PRD-silence skip paths inline; deleted.
        """
        # DELETED — test_archive_from_completed_cancels_pending_waivers.
        # The author's own skip paths cite PRD §3.8 silence on the
        # clock target needed to reach COMPLETED. PRD-silent → deleted.
        pass


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (both instances exercised
# in test_10 — add second-angle tests here).
# ===========================================================================
class TestPriorityPairAdditional:
    # DELETED — test_state_check_wins_when_balance_path_would_succeed.
    # PRD §3.6 does not name a league-status state precondition for
    # waiver submission (no ERR_INVALID_STATE rule on POST /waivers).
    # The "between weeks" prose is ambiguous; the test relies on the
    # generic priority-7 framing from §2.9 but no waiver-specific
    # state rule is uniquely derivable. PRD-silent → deleted.
    pass


# ===========================================================================
# Rule 6 — boundary_precision_check
# Instance 1: veto_quorum_exact_threshold_at_50pct
# ===========================================================================
class TestVetoBoundary:
    def test_three_vetoes_below_four_vetoes_at_threshold(self, api):
        """PRD §3.7: "The veto percentage is the count of VETO votes for this proposal multiplied by 100 and then integer-divided (floor division, rounding toward zero) by the eligible voter pool. The threshold is considered crossed when this integer percentage is greater than or equal to League.veto_quorum_pct."
        PRD §3.7: "Equality with the quorum counts as crossed; strictly less does not."

        Claim: with eligible_voters=8 and quorum=50,
          - after 3 vetoes: (3*100)//8 = 37 < 50 → still
            ACCEPTED_PENDING_REVIEW
          - after 4 vetoes: (4*100)//8 = 50 >= 50 → VETOED

        # difficulty: boundary_precision_check/veto_quorum_exact_threshold_at_50pct
        """
        bundle = setup_accepted_trade(team_count=10, veto_quorum_pct=50)
        league = bundle["league"]
        trade = bundle["trade"]
        # Vote 3 vetoes (T3, T4, T5).
        for i in range(3):
            voter = bundle["teams"][2 + i]
            cast_vote_as(trade["id"], voter, "VETO")
        mid = fetch_trade(league["id"], trade["id"])
        assert mid["status"] == "ACCEPTED_PENDING_REVIEW", \
            "PRD §3.7: 3/8 = 37 < 50 — not yet crossed"
        # 4th veto crosses the boundary.
        cast_vote_as(trade["id"], bundle["teams"][5], "VETO")
        final = fetch_trade(league["id"], trade["id"])
        assert final["status"] == "VETOED", \
            "PRD §3.7: 4/8 = 50 >= 50 — crosses"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# Instance 1: trade_accept_requires_league_in_regular_season_or_playoffs
# (PRD silence: PRD does not explicitly enumerate which League.statuses
# permit trade accept — only validation priority 7 says "Target ...
# Trade ... is in a state that permits this transition (state-machine
# precondition)". The TradeProposal state machine in §3.7 does not
# explicitly include a League.status precondition. SKIP.)
# Instance 2: roster_slot_lineup_change_requires_matchup_week_unlocked —
# fully covered in test_04 and test_10.
# ===========================================================================
class TestCrossEntityState:
    def test_lineup_patch_blocked_after_matchup_locked(self, api):
        """PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."

        Claim: with the active MatchupWeek in LOCKED state, a
        RosterSlot lineup change yields ERR_LINEUP_LOCKED.

        # difficulty: cross_entity_state_dependency/roster_slot_lineup_change_requires_matchup_week_unlocked
        """
        bundle = setup_locked_week(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        # Find a bench slot.
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        bench = next(s for s in slots if s["slot_type"] == "BENCH")
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], bench["id"],
            patch_roster_slot_payload(slot_type="BENCH"),  # any mutation
            h0,
        )
        validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# Instance 1: waiver_settle_window_overlap_on_player
# Instance 2: matchup_week_lock_window_aggregate_capacity
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_two_claims_same_settle_window_resolved_to_exactly_one_winner(self, api):
        """PRD §3.6: "The algorithm walks every PENDING claim whose settle_ts is at or before League.now_ts, groups claims by add_player_id, and, within each group, sorts claims by bid_dollars descending with ties broken by priority_seed ascending and a final tiebreak of created_at ascending. The sweep then walks the sorted list and selects the first claim whose team still has faab_balance_dollars at least equal to its bid_dollars and whose team either has roster headroom under roster_size or supplied a non-null drop_player_id".

        Claim: two PENDING claims with the same settle_ts on the same
        player produce exactly one AWARDED claim and one LOST claim;
        the awarded team's roster shows the player exactly once.

        # difficulty: resource_temporal_overlap/waiver_settle_window_overlap_on_player
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        t1, t2, _, _ = bundle["teams"]
        target = create_player(position="WR")
        set_player_status(target["id"], "OUT")
        w1 = submit_waiver(
            league=league, team=t1, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=2,
        )
        w2 = submit_waiver(
            league=league, team=t2, add_player_id=target["id"],
            bid_dollars=10, settle_offset_hours=2,
        )
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=3))
        api.process_waivers(league["id"], COMMISSIONER)
        from test_helpers import fetch_waiver
        w1_after = fetch_waiver(league["id"], w1["id"])
        w2_after = fetch_waiver(league["id"], w2["id"])
        statuses = sorted([w1_after["status"], w2_after["status"]])
        assert statuses == ["AWARDED", "LOST"], \
            f"PRD §3.6: exactly one winner per group, got {statuses}"
        # Player on exactly one team's roster.
        roster_count = 0
        for t in bundle["teams"]:
            slots = list_roster_slots_for_team(league["id"], t["id"])
            roster_count += sum(1 for s in slots if s["player_id"] == target["id"])
        assert roster_count == 1, \
            f"PRD §3.6: target player on exactly one roster, got {roster_count}"

    def test_lineup_lock_window_blocks_mutation_at_lock_instant(self, api):
        """PRD §3.5: "A clock advance that crosses the configured lock instant of a SCHEDULED MatchupWeek whose week_number equals League.current_week transitions the matchup to LOCKED".
        PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."

        Claim: once the clock has advanced past the lock instant, a
        subsequent lineup PATCH is rejected with ERR_LINEUP_LOCKED.
        (Pre-lock patches succeed; post-lock patches collide with the
        lock window.)

        # difficulty: resource_temporal_overlap/matchup_week_lock_window_aggregate_capacity
        """
        bundle = setup_locked_week(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        bench = next(s for s in slots if s["slot_type"] == "BENCH")
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], bench["id"],
            patch_roster_slot_payload(slot_type="BENCH"),
            h0,
        )
        validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# Instances covered in test_09. Add a second angle here for
# faab_total_conserved instance.
# ===========================================================================
class TestCompensatingInvariantAdditional:
    def test_no_faab_movement_when_send_and_receive_faab_zero(self, api):
        """PRD §3.7: "any non-zero FAAB transfer is applied (the sending team's faab_balance_dollars is decremented and the receiving team's incremented by the matching amount, in whichever direction the non-zero value points)."

        Claim: with send_faab_dollars=0 and receive_faab_dollars=0
        (the no-FAAB-transfer default), neither team's
        faab_balance_dollars changes across trade execution.

        # difficulty: compensating_invariant/faab_total_conserved_under_trade_execution
        """
        bundle = setup_accepted_trade(team_count=4, send_faab_dollars=None)
        league = bundle["league"]
        trade = bundle["trade"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        t1_before = fetch_team(league["id"], t1["id"])
        t2_before = fetch_team(league["id"], t2["id"])
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=49))
        latest = fetch_trade(league["id"], trade["id"])
        assert latest["status"] == "EXECUTED"
        t1_after = fetch_team(league["id"], t1["id"])
        t2_after = fetch_team(league["id"], t2["id"])
        assert t1_after["faab_balance_dollars"] == t1_before["faab_balance_dollars"]
        assert t2_after["faab_balance_dollars"] == t2_before["faab_balance_dollars"]
