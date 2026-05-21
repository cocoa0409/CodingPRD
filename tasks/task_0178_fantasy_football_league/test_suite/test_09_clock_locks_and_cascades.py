"""Clock advance, weekly locks, injury replacement, and trade-execution
cascades.

Covers PRD §2.5 (logical clock semantics), §3.5 (LOCKED transition and
injury replacement), §3.7 (trade EXECUTED side effects), §3.8 (archive
cascade).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    accept_trade_as,
    advance_clock_to,
    create_player,
    DEFAULT_BASE_CLOCK,
    fetch_team,
    fetch_trade,
    iso_utc,
    list_matchups,
    list_roster_slots_for_team,
    make_manager_headers,
    propose_trade,
    set_player_status,
    setup_accepted_trade,
    setup_drafted_league,
    setup_locked_week,
    validate_error,
    validate_success,
)


def _now(league):
    return datetime.fromisoformat(league["now_ts"].replace("Z", "+00:00"))


# ===========================================================================
# Clock-advance: lock side-effect (PRD §3.5)
# ===========================================================================
class TestWeeklyLock:
    def test_clock_past_lock_transitions_matchup_to_locked(self, api):
        """PRD §3.5: "A clock advance that crosses the configured lock instant of a SCHEDULED MatchupWeek whose week_number equals League.current_week transitions the matchup to LOCKED, provided the league is currently in REGULAR_SEASON or PLAYOFFS."

        Claim: a clock advance past the week-1 lock instant turns at
        least one week-1 MatchupWeek row from SCHEDULED to LOCKED.
        """
        bundle = setup_locked_week(team_count=4)
        matchups = bundle["matchups_week_1"]
        assert any(m["status"] == "LOCKED" for m in matchups), \
            "PRD §3.5: clock past lock → MatchupWeek.status = LOCKED"


# ===========================================================================
# Injury replacement — PRD §3.5
# ===========================================================================
class TestInjuryReplacement:
    def test_out_starter_swapped_with_best_bench_candidate(self, api):
        """PRD §3.5: "While snapshotting, the system runs injury replacement: for every starter slot whose Player.status_tag is OUT, the system searches that team's bench for a replacement candidate. A candidate is any BENCH RosterSlot on the same team whose player has a status_tag that is neither OUT nor IR_ELIGIBLE and whose position is eligible for the starter's position_label."
        PRD §3.5: "The swap exchanges both slot_type and position_label between the injured starter slot and the chosen bench slot, so the bench player becomes the starter and the injured player moves to the bench."

        Claim: when a starter is OUT and a same-position BENCH player
        is ACTIVE, lock swaps them — bench → STARTER, starter → BENCH.

        # difficulty: transitive_cascade/matchup_lock_two_hop_injury_replacement
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        starter_rb_slot = None
        for s in slots:
            if s.get("slot_type") != "STARTER":
                continue
            pl = s.get("position_label") or ""
            if pl.startswith("RB"):
                pdata = players_by_id.get(s["player_id"])
                if pdata and pdata.get("position") == "RB":
                    starter_rb_slot = s
                    break
        assert starter_rb_slot is not None, "Expected an RB starter slot"
        bench_rb_slot = None
        for s in slots:
            if s.get("slot_type") != "BENCH":
                continue
            pdata = players_by_id.get(s["player_id"])
            if pdata and pdata.get("position") == "RB":
                bench_rb_slot = s
                break
        assert bench_rb_slot is not None, "Expected at least one BENCH RB"
        set_player_status(starter_rb_slot["player_id"], "OUT", weekly_proj_points=0.0)
        set_player_status(bench_rb_slot["player_id"], "ACTIVE", weekly_proj_points=12.0)
        advance_clock_to(
            league["id"], DEFAULT_BASE_CLOCK + timedelta(days=7, hours=24),
        )
        after = list_roster_slots_for_team(league["id"], t0["id"])
        after_by_id = {s["id"]: s for s in after}
        new_starter = after_by_id[bench_rb_slot["id"]]
        new_bench = after_by_id[starter_rb_slot["id"]]
        assert new_starter["slot_type"] == "STARTER", \
            "PRD §3.5: bench player becomes the starter"
        assert new_bench["slot_type"] == "BENCH", \
            "PRD §3.5: injured player moves to the bench"
        assert new_starter.get("position_label") == starter_rb_slot.get("position_label"), \
            "PRD §3.5: 'The swap exchanges both slot_type and position_label'"

    def test_no_replacement_keeps_starter_in_place(self, api):
        """PRD §3.5: "If no candidate exists, the injured starter remains a starter and contributes 0 to the team's scoring that week."

        Claim: when the bench has no eligible same-position non-OUT
        replacement, the OUT starter stays STARTER and the
        starter's position_label is unchanged.

        # difficulty: boundary_precision_check/empty_candidate_set_in_injury_replacement
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        starter_rb_slot = None
        for s in slots:
            if s.get("slot_type") == "STARTER" and (s.get("position_label") or "").startswith("RB"):
                starter_rb_slot = s
                break
        assert starter_rb_slot is not None
        # Mark every BENCH RB on this team OUT (and FLEX-eligible
        # BENCH WR/TE that could substitute in a FLEX slot — but the
        # current starter is RB1 (strict label), so only RB candidates
        # are eligible).
        for s in slots:
            if s.get("slot_type") != "BENCH":
                continue
            pdata = players_by_id.get(s["player_id"])
            if pdata and pdata.get("position") == "RB":
                set_player_status(s["player_id"], "OUT")
        # Mark starter OUT to trigger replacement search.
        set_player_status(starter_rb_slot["player_id"], "OUT")
        advance_clock_to(
            league["id"], DEFAULT_BASE_CLOCK + timedelta(days=7, hours=24),
        )
        after = list_roster_slots_for_team(league["id"], t0["id"])
        after_by_id = {s["id"]: s for s in after}
        starter_after = after_by_id[starter_rb_slot["id"]]
        assert starter_after["slot_type"] == "STARTER", \
            "PRD §3.5: 'If no candidate exists, the injured starter remains a starter'"
        assert starter_after.get("position_label") == starter_rb_slot.get("position_label"), \
            "PRD §3.5: with no candidate, no slot swap occurs"

    def test_injury_replacement_swaps_strict_position_label(self, api):
        """PRD §3.5: "for any strict starter label (QB1, RB1, RB2, WR1, WR2, WR3, TE1, K1, DST1), the candidate's Player.position must match the slot's label root (RB for RB1 or RB2, WR for any WR label, and so on)".

        Claim: an OUT WR1 starter with a healthy BENCH WR is swapped;
        the replacement carries the WR1 position_label.

        # difficulty: transitive_cascade/matchup_lock_two_hop_injury_replacement
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        starter_wr = None
        for s in slots:
            if s.get("slot_type") == "STARTER" and (s.get("position_label") or "").startswith("WR"):
                pdata = players_by_id.get(s["player_id"])
                if pdata and pdata.get("position") == "WR":
                    starter_wr = s
                    break
        assert starter_wr is not None
        bench_wr = None
        for s in slots:
            if s.get("slot_type") == "BENCH":
                pdata = players_by_id.get(s["player_id"])
                if pdata and pdata.get("position") == "WR":
                    bench_wr = s
                    break
        assert bench_wr is not None
        set_player_status(starter_wr["player_id"], "OUT")
        set_player_status(bench_wr["player_id"], "ACTIVE", weekly_proj_points=8.0)
        advance_clock_to(
            league["id"], DEFAULT_BASE_CLOCK + timedelta(days=7, hours=24),
        )
        after = list_roster_slots_for_team(league["id"], t0["id"])
        after_by_id = {s["id"]: s for s in after}
        new_starter = after_by_id[bench_wr["id"]]
        assert new_starter["slot_type"] == "STARTER"
        # The label must equal the original starter's WR# label.
        assert new_starter.get("position_label") == starter_wr.get("position_label"), \
            "PRD §3.5: 'The swap exchanges both slot_type and position_label'"


# ===========================================================================
# Trade execution cascade (PRD §3.7 / §3.6)
# ===========================================================================
class TestTradeExecutionEffects:
    def test_trade_executed_moves_players_to_bench(self, api):
        """PRD §3.7: "the trade transitions to EXECUTED and its side-effects fan out: each send_player_ids entry is moved to the counterparty's roster as BENCH with position_label null, each receive_player_ids entry is moved to the proposer's roster as BENCH with position_label null".

        Claim: after EXECUTED, the swapped players are on the other
        team as BENCH (position_label is null).

        # difficulty: compensating_invariant/roster_player_count_conserved_under_trade_execution
        """
        bundle = setup_accepted_trade(team_count=4, trade_review_hours=48)
        league = bundle["league"]
        trade = bundle["trade"]
        p_send = bundle["p_send"]
        p_recv = bundle["p_recv"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        # Snapshot total roster slot counts league-wide before
        # execution to verify conservation.
        sum_before = sum(
            len(list_roster_slots_for_team(league["id"], t["id"]))
            for t in bundle["teams"]
        )
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=49))
        latest = fetch_trade(league["id"], trade["id"])
        assert latest["status"] == "EXECUTED"
        t1_slots = list_roster_slots_for_team(league["id"], t1["id"])
        t2_slots = list_roster_slots_for_team(league["id"], t2["id"])
        # Receive side: p_recv on T1, BENCH, position_label null.
        recv_slot = next(s for s in t1_slots if s["player_id"] == p_recv["id"])
        assert recv_slot["slot_type"] == "BENCH"
        assert recv_slot.get("position_label") is None
        # Send side: p_send on T2, BENCH, position_label null.
        send_slot = next(s for s in t2_slots if s["player_id"] == p_send["id"])
        assert send_slot["slot_type"] == "BENCH"
        assert send_slot.get("position_label") is None
        # Roster-count conservation (difficulty Rule 9 instance 2).
        sum_after = sum(
            len(list_roster_slots_for_team(league["id"], t["id"]))
            for t in bundle["teams"]
        )
        assert sum_before == sum_after, \
            "PRD §3.7: trade execution preserves total RosterSlot count"

    def test_faab_total_conserved_across_executed_trade(self, api):
        """PRD §3.7: "any non-zero FAAB transfer is applied (the sending team's faab_balance_dollars is decremented and the receiving team's incremented by the matching amount, in whichever direction the non-zero value points)."

        Claim: with send_faab_dollars > 0, the league-wide sum of
        Team.faab_balance_dollars is conserved across the trade
        execution.

        # difficulty: compensating_invariant/faab_total_conserved_under_trade_execution
        """
        bundle = setup_accepted_trade(team_count=4, send_faab_dollars=25)
        league = bundle["league"]
        trade = bundle["trade"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        sum_before = sum(
            fetch_team(league["id"], t["id"])["faab_balance_dollars"]
            for t in bundle["teams"]
        )
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=49))
        sum_after = sum(
            fetch_team(league["id"], t["id"])["faab_balance_dollars"]
            for t in bundle["teams"]
        )
        assert sum_before == sum_after, \
            f"PRD §3.7: Σ FAAB conserved across executed trade ({sum_before} != {sum_after})"
        t1_after = fetch_team(league["id"], t1["id"])
        t2_after = fetch_team(league["id"], t2["id"])
        # T1 was the proposer sending FAAB.
        assert t1_after["faab_balance_dollars"] == 100 - 25
        assert t2_after["faab_balance_dollars"] == 100 + 25
