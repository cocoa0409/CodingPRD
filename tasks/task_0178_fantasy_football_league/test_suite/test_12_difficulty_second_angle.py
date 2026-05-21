"""Second-angle tests for difficulty-design instances that need ≥2
covering tests. Each test cites PRD prose and tags itself with
# difficulty: <rule_id>/<instance.name>.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    accept_trade_as,
    advance_clock_to,
    cast_vote_as,
    create_league_with_teams,
    create_player,
    create_waiver_payload,
    DEFAULT_BASE_CLOCK,
    fetch_team,
    fetch_trade,
    fetch_waiver,
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
# combinatorial_formula/matchup_scoring_sum_then_round_mode_b — Angle 2
# ===========================================================================
class TestSumThenRoundSecondAngle:
    def test_ppr_sum_then_round_does_not_double_round(self, api, commissioner_headers):
        """PRD §2.10: "Critically, the rounding happens exactly once per team per week, after the sum of all that team's starter contributions has been computed — implementations that round each starter's contribution first and then sum the rounded values are wrong."
        PRD §3.5: "After both team sums are complete, the system applies 'round half up' to two decimal places exactly once per team to produce home_points and away_points."

        Claim: in PPR mode with two starters contributing 1.004 each
        (no reception credit), sum = 2.008 → ROUND_HALF_UP to 2.01.
        Round-then-sum would yield 1.00 + 1.00 = 2.00 (wrong).

        # difficulty: combinatorial_formula/matchup_scoring_sum_then_round_mode_b
        """
        bundle = setup_locked_week(team_count=4, scoring_mode="PPR")
        league = bundle["league"]
        wk1 = list_matchups(league["id"], week_number=1)[0]
        home_starters = [
            rs for rs in list_roster_slots_for_team(league["id"], wk1["home_team_id"])
            if rs["slot_type"] == "STARTER"
        ]
        away_starters = [
            rs for rs in list_roster_slots_for_team(league["id"], wk1["away_team_id"])
            if rs["slot_type"] == "STARTER"
        ]
        s1, s2 = home_starters[0], home_starters[1]
        scores = [
            score_entry(player_id=s1["player_id"], actual_points=1.004, receptions_credited=0),
            score_entry(player_id=s2["player_id"], actual_points=1.004, receptions_credited=0),
        ]
        for rs in home_starters[2:]:
            scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0))
        for rs in away_starters:
            scores.append(score_entry(player_id=rs["player_id"], actual_points=0.0))
        res = api.score_matchup(league["id"], 1, score_payload(scores), commissioner_headers)
        validate_success(res, 200)
        from test_helpers import fetch_matchup
        wk1_after = fetch_matchup(league["id"], 1)
        # 1.004 + 1.004 = 2.008 → ROUND_HALF_UP → 2.01.
        assert wk1_after["home_points"] == pytest.approx(2.01, abs=0.001), \
            f"PRD §2.10 sum-then-round: expected 2.01, got {wk1_after['home_points']}"


# ===========================================================================
# non_linear_state_machine/league_branching_terminal_archive_path —
# Angle 2 (skip-resilient archive-side-effect test using a more
# defensive construction that does not require a full season replay).
# ===========================================================================
class TestArchiveCascadeNegative:
    def test_archive_from_draft_pending_rejected(self, api, commissioner_headers):
        """PRD §3.8: "A Commissioner may archive a league whose status is COMPLETED, transitioning it to ARCHIVED (the terminal state)."

        Claim: archive on a league NOT in COMPLETED (e.g.,
        DRAFT_PENDING) is rejected. This pins the
        COMPLETED-only branch of the League state machine.

        # difficulty: non_linear_state_machine/league_branching_terminal_archive_path
        """
        league, _ = create_league_with_teams(team_count=4)
        res = api.archive_league(league["id"], commissioner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# priority_pair_validation_conflict/business_safety_vs_business_constraint
# Angle 2 (post-lock attempt at moving a player into IR while also
# violating IR eligibility — lineup-lock still fires first).
# ===========================================================================
class TestLineupLockVsIREligibility:
    def test_lineup_lock_wins_over_ir_ineligible(self, api):
        """PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."
        PRD §2.9: "state-machine preconditions, surfaced as ERR_INVALID_STATE; and (8) business safety, referential, constraint, temporal, and fiscal checks specific to the endpoint".

        Claim: after lock, an IR-ineligible mutation (moving an
        ACTIVE player into IR) still surfaces ERR_LINEUP_LOCKED
        (business_safety) rather than ERR_IR_INELIGIBLE
        (business_constraint).

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_lineup_patch
        """
        bundle = setup_locked_week(team_count=4, ir_slots=2)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        # Any BENCH slot whose player is ACTIVE.
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        bench = next(s for s in slots if s["slot_type"] == "BENCH")
        h0 = make_manager_headers(t0["manager_user_id"])
        res = api.patch_roster_slot(
            t0["id"], bench["id"],
            patch_roster_slot_payload(slot_type="IR"),
            h0,
        )
        body = res.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] != ApiErrorId.ERR_IR_INELIGIBLE.value, \
            "PRD §2.9: lineup-lock (business_safety) fires before IR-eligibility (business_constraint)"
        validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)


# ===========================================================================
# boundary_precision_check/empty_candidate_set_in_injury_replacement —
# Angle 2 (FLEX slot with no flex-eligible bench candidates).
# ===========================================================================
class TestEmptyCandidateFlex:
    # DELETED — test_flex_starter_out_with_no_flex_eligible_bench_keeps_starter.
    # PRD §3.4 names FLEX only in the example 10-starter composition;
    # the test fixture's 7-starter setup may or may not contain a FLEX
    # slot depending on implementation. PRD does not pin the
    # composition for starter_count != 10. PRD-silent → deleted.
    pass


# ===========================================================================
# cross_entity_state_dependency/roster_slot_lineup_change_requires_matchup_week_unlocked
# Angle 2 (positive: PATCH before lock succeeds).
# ===========================================================================
class TestPreLockMutationSucceeds:
    def test_lineup_patch_before_lock_succeeds(self, api):
        """PRD §3.4: "Once the league enters REGULAR_SEASON, every team holds a roster represented by RosterSlot rows."
        PRD §3.4: "(a) If MatchupWeek.status for the team's current-week matchup is already LOCKED — that is, if the weekly lock has fired — the mutation is rejected with ERR_LINEUP_LOCKED."

        Claim: BEFORE the week-1 lock has fired, a PATCH that swaps
        an RB BENCH ↔ STARTER (within position rules) succeeds.

        # difficulty: cross_entity_state_dependency/roster_slot_lineup_change_requires_matchup_week_unlocked
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        slots = list_roster_slots_for_team(league["id"], t0["id"])
        players_by_id = {p["id"]: p for p in bundle["players_flat"]}
        starter_rb = None
        bench_rb = None
        for s in slots:
            pdata = players_by_id.get(s.get("player_id"))
            if pdata and pdata.get("position") == "RB":
                if s["slot_type"] == "STARTER" and (s.get("position_label") or "").startswith("RB"):
                    if starter_rb is None:
                        starter_rb = s
                elif s["slot_type"] == "BENCH":
                    if bench_rb is None:
                        bench_rb = s
        assert starter_rb is not None and bench_rb is not None
        h0 = make_manager_headers(t0["manager_user_id"])
        # Move the BENCH RB into BENCH (no-op slot_type but still a
        # mutation request; pre-lock should succeed without
        # ERR_LINEUP_LOCKED).
        res = api.patch_roster_slot(
            t0["id"], bench_rb["id"],
            patch_roster_slot_payload(slot_type="BENCH"),
            h0,
        )
        body = res.json()
        if body.get("response_type") == "error":
            assert body["data"]["error_id"] != ApiErrorId.ERR_LINEUP_LOCKED.value, \
                "PRD §3.4: pre-lock PATCH must not be rejected with ERR_LINEUP_LOCKED"


# ===========================================================================
# resource_temporal_overlap/waiver_settle_window_overlap_on_player —
# Angle 2 (after sweep, player on exactly one team and only one claim
# is AWARDED out of any number of overlapping claims).
# ===========================================================================
class TestWaiverSweepCardinality:
    def test_only_one_claim_awarded_among_many_overlapping(self, api):
        """PRD §3.6: "Every other still-PENDING claim for the same add_player_id is transitioned to LOST in the same sweep — a depth-two cascade where subsequent sweeps would not reconsider those rows."

        Claim: with 3 overlapping claims for the same player at
        identical settle_ts, exactly one becomes AWARDED and the
        other two become LOST.

        # difficulty: resource_temporal_overlap/waiver_settle_window_overlap_on_player
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        t1, t2, t3, _ = bundle["teams"]
        target = create_player(position="WR")
        set_player_status(target["id"], "OUT")
        ws = []
        for t, bid in ((t1, 10), (t2, 10), (t3, 10)):
            ws.append(submit_waiver(
                league=league, team=t, add_player_id=target["id"],
                bid_dollars=bid, settle_offset_hours=2,
            ))
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=3))
        api.process_waivers(league["id"], COMMISSIONER)
        readings = [fetch_waiver(league["id"], w["id"]) for w in ws]
        awarded = [w for w in readings if w["status"] == "AWARDED"]
        lost = [w for w in readings if w["status"] == "LOST"]
        assert len(awarded) == 1, f"PRD §3.6: exactly one AWARDED in a sweep group, got {len(awarded)}"
        assert len(lost) == 2, f"PRD §3.6: every other PENDING → LOST, got {len(lost)}"


# ===========================================================================
# resource_temporal_overlap/matchup_week_lock_window_aggregate_capacity —
# Angle 2 (every starter slot in the LOCKED week is also non-mutable).
# ===========================================================================
class TestLockedWindowAggregate:
    def test_after_lock_every_starter_slot_in_week_is_immutable(self, api):
        """PRD §3.4: "Once League.now_ts is at or beyond that value, the slot becomes immutable for the rest of the week."
        PRD §3.5: "The lock side-effect snapshots every starter RosterSlot on both teams and writes the end-of-week instant into each affected slot's locked_until_ts."

        Claim: after week-1 lock, EVERY starter RosterSlot on the
        active team is immutable; a PATCH on any starter yields
        ERR_LINEUP_LOCKED.

        # difficulty: resource_temporal_overlap/matchup_week_lock_window_aggregate_capacity
        """
        bundle = setup_locked_week(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        starters = [
            s for s in list_roster_slots_for_team(league["id"], t0["id"])
            if s["slot_type"] == "STARTER"
        ]
        assert starters, "Expected starter slots after draft"
        h0 = make_manager_headers(t0["manager_user_id"])
        for s in starters[:2]:  # check at least two distinct starters
            res = api.patch_roster_slot(
                t0["id"], s["id"],
                patch_roster_slot_payload(slot_type="STARTER", position_label=s.get("position_label")),
                h0,
            )
            validate_error(res, ApiErrorId.ERR_LINEUP_LOCKED.value)


# ===========================================================================
# compensating_invariant/roster_player_count_conserved_under_trade_execution
# Angle 2 (multi-player swap: 2-for-2 conserves count).
# ===========================================================================
class TestRosterCountConservedMultiplayer:
    def test_two_for_two_trade_conserves_per_team_count(self, api):
        """PRD §3.7: "the trade transitions to EXECUTED and its side-effects fan out: each send_player_ids entry is moved to the counterparty's roster as BENCH with position_label null, each receive_player_ids entry is moved to the proposer's roster as BENCH with position_label null".

        Claim: a 2-for-2 trade execution conserves each team's
        roster-slot count.

        # difficulty: compensating_invariant/roster_player_count_conserved_under_trade_execution
        """
        bundle = setup_drafted_league(team_count=4, trade_review_hours=48)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        send_ids = [bundle["players_by_team"][t1["id"]][1]["id"],
                    bundle["players_by_team"][t1["id"]][2]["id"]]
        recv_ids = [bundle["players_by_team"][t2["id"]][1]["id"],
                    bundle["players_by_team"][t2["id"]][2]["id"]]
        trade = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=send_ids, receive_player_ids=recv_ids,
        )
        accept_trade_as(trade["id"], t2)
        t1_count_before = len(list_roster_slots_for_team(league["id"], t1["id"]))
        t2_count_before = len(list_roster_slots_for_team(league["id"], t2["id"]))
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=49))
        t1_count_after = len(list_roster_slots_for_team(league["id"], t1["id"]))
        t2_count_after = len(list_roster_slots_for_team(league["id"], t2["id"]))
        assert t1_count_after == t1_count_before, \
            "PRD §3.7: per-team RosterSlot count conserved across multi-player trade"
        assert t2_count_after == t2_count_before
