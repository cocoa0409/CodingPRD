"""Trade lifecycle, veto voting, and review-deadline execution.

Covers PRD §3.7 — propose / accept / reject / cancel, votes, veto
threshold, EXECUTED / EXPIRED on clock advance.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    accept_trade_as,
    advance_clock_to,
    cancel_trade_as,
    cast_vote_as,
    create_trade_payload,
    fetch_team,
    fetch_trade,
    iso_utc,
    list_roster_slots_for_team,
    make_manager_headers,
    propose_trade,
    reject_trade_as,
    setup_accepted_trade,
    setup_drafted_league,
    validate_error,
    validate_success,
)


def _now(league):
    return datetime.fromisoformat(league["now_ts"].replace("Z", "+00:00"))


# ===========================================================================
# Trade creation validation — PRD §3.7
# ===========================================================================
class TestTradeCreate:
    def test_two_way_faab_rejected(self, api):
        """PRD §3.7: "At most one direction of FAAB may be non-zero: a proposal where both send_faab_dollars and receive_faab_dollars are non-zero is rejected with ERR_TWO_WAY_FAAB_FORBIDDEN."

        Claim: a trade with both send_faab_dollars > 0 AND
        receive_faab_dollars > 0 is rejected.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        payload = create_trade_payload(
            proposing_team_id=t1["id"],
            counterparty_team_id=t2["id"],
            send_player_ids=[p_send["id"]],
            receive_player_ids=[p_recv["id"]],
            send_faab_dollars=5,
            receive_faab_dollars=5,
        )
        headers = make_manager_headers(t1["manager_user_id"])
        res = api.create_trade(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_TWO_WAY_FAAB_FORBIDDEN.value)

    def test_send_player_not_on_proposer_roster_rejected(self, api):
        """PRD §3.7: "A send-side or receive-side player who is not currently on the relevant team's roster is rejected with ERR_PLAYER_NOT_ON_ROSTER".

        Claim: send_player_ids referring to a player NOT on the
        proposer's roster yields ERR_PLAYER_NOT_ON_ROSTER.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        # Use a player from t2's roster as the "send" id from t1.
        impostor = bundle["players_by_team"][t2["id"]][2]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        payload = create_trade_payload(
            proposing_team_id=t1["id"],
            counterparty_team_id=t2["id"],
            send_player_ids=[impostor["id"]],
            receive_player_ids=[p_recv["id"]],
        )
        headers = make_manager_headers(t1["manager_user_id"])
        res = api.create_trade(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_PLAYER_NOT_ON_ROSTER.value)


# ===========================================================================
# Accept / reject / cancel — PRD §3.7
# ===========================================================================
class TestTradeResponse:
    def test_accept_by_counterparty_transitions_to_accepted_pending_review(self, api):
        """PRD §3.7: "Accepting transitions the proposal from OFFERED to ACCEPTED_PENDING_REVIEW and is permitted only to a manager whose team equals counterparty_team_id; at acceptance time the system re-checks that all send_player_ids are still on the proposer's roster, all receive_player_ids are still on the counterparty's roster, and the proposer's faab_balance_dollars is at least send_faab_dollars and the counterparty's is at least receive_faab_dollars."

        Claim: a counterparty acceptance moves the trade to
        ACCEPTED_PENDING_REVIEW and sets review_deadline_ts.
        """
        bundle = setup_accepted_trade(team_count=4)
        trade = bundle["trade"]
        assert trade["status"] == "ACCEPTED_PENDING_REVIEW"
        assert trade.get("review_deadline_ts"), \
            "PRD §3.7: review_deadline_ts must be set on acceptance"

    def test_proposer_cannot_accept_their_own_trade(self, api):
        """PRD §3.7: "Accepting transitions the proposal from OFFERED to ACCEPTED_PENDING_REVIEW and is permitted only to a manager whose team equals counterparty_team_id".

        Claim: the proposer attempting to accept is rejected with
        ERR_NOT_TEAM_OWNER.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        trade = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send["id"]], receive_player_ids=[p_recv["id"]],
        )
        h_proposer = make_manager_headers(t1["manager_user_id"])
        res = api.accept_trade(trade["id"], h_proposer)
        validate_error(res, ApiErrorId.ERR_NOT_TEAM_OWNER.value)

    def test_counterparty_rejects_offered_trade(self, api):
        """PRD §3.7: "Rejecting transitions to REJECTED and is also restricted to the counterparty."

        Claim: counterparty rejection moves the trade to REJECTED.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        trade = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send["id"]], receive_player_ids=[p_recv["id"]],
        )
        rejected = reject_trade_as(trade["id"], t2)
        assert rejected["status"] == "REJECTED"

    def test_proposer_cancels_offered_trade(self, api):
        """PRD §3.7: "Canceling transitions to CANCELED and is restricted to the proposer; once the trade has moved past OFFERED, the proposer can no longer cancel."

        Claim: proposer can cancel while OFFERED → CANCELED.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        trade = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send["id"]], receive_player_ids=[p_recv["id"]],
        )
        cancelled = cancel_trade_as(trade["id"], t1)
        assert cancelled["status"] == "CANCELED"


# ===========================================================================
# Vote eligibility — PRD §3.7
# ===========================================================================
class TestVoteEligibility:
    def test_proposer_cannot_vote_eligible_voter_rejected(self, api):
        """PRD §3.7: "A vote from the proposer or counterparty, or a second vote from a team that has already voted on this trade, is rejected with ERR_NOT_ELIGIBLE_VOTER."

        Claim: the proposer attempting to vote is rejected with
        ERR_NOT_ELIGIBLE_VOTER.
        """
        bundle = setup_accepted_trade(team_count=4)
        league = bundle["league"]
        trade = bundle["trade"]
        t1 = bundle["teams"][0]  # proposer
        from test_helpers import trade_vote_payload
        payload = trade_vote_payload(voting_team_id=t1["id"], vote="VETO")
        headers = make_manager_headers(t1["manager_user_id"])
        res = api.cast_trade_vote(trade["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_NOT_ELIGIBLE_VOTER.value)

    def test_double_voting_rejected(self, api):
        """PRD §3.7: "A vote from the proposer or counterparty, or a second vote from a team that has already voted on this trade, is rejected with ERR_NOT_ELIGIBLE_VOTER."

        Claim: a team voting twice on the same trade is rejected.
        """
        bundle = setup_accepted_trade(team_count=4)
        league = bundle["league"]
        trade = bundle["trade"]
        t3 = bundle["teams"][2]  # non-party voter
        first = cast_vote_as(trade["id"], t3, "APPROVE")
        # Second vote by same team.
        from test_helpers import trade_vote_payload
        headers = make_manager_headers(t3["manager_user_id"])
        res = api.cast_trade_vote(
            trade["id"], trade_vote_payload(voting_team_id=t3["id"], vote="VETO"),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_ELIGIBLE_VOTER.value)

    def test_vote_on_non_accepted_pending_review_trade_rejected(self, api):
        """PRD §3.7: "A vote cast on a trade that is not in ACCEPTED_PENDING_REVIEW (because it is still OFFERED, or already VETOED, EXECUTED, REJECTED, EXPIRED, or CANCELED) is rejected with ERR_TRADE_NOT_OPEN_FOR_VOTING."

        Claim: voting on an OFFERED trade (still pre-accept) yields
        ERR_TRADE_NOT_OPEN_FOR_VOTING.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t1, t2 = bundle["teams"][0], bundle["teams"][1]
        t3 = bundle["teams"][2]
        p_send = bundle["players_by_team"][t1["id"]][1]
        p_recv = bundle["players_by_team"][t2["id"]][1]
        trade = propose_trade(
            league=league, proposing_team=t1, counterparty_team=t2,
            send_player_ids=[p_send["id"]], receive_player_ids=[p_recv["id"]],
        )
        # Trade is OFFERED, never accepted.
        from test_helpers import trade_vote_payload
        headers = make_manager_headers(t3["manager_user_id"])
        res = api.cast_trade_vote(
            trade["id"], trade_vote_payload(voting_team_id=t3["id"], vote="VETO"),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_TRADE_NOT_OPEN_FOR_VOTING.value)


# ===========================================================================
# Veto threshold — PRD §3.7
# ===========================================================================
class TestVetoThreshold:
    def test_veto_floor_div_below_threshold_keeps_trade_open(self, api):
        """PRD §3.7: "The veto percentage is the count of VETO votes for this proposal multiplied by 100 and then integer-divided (floor division, rounding toward zero) by the eligible voter pool. The threshold is considered crossed when this integer percentage is greater than or equal to League.veto_quorum_pct."

        Claim: with team_count=10 and veto_quorum_pct=50, eligible
        voters = 8; 3 vetoes → (3*100)//8 = 37 < 50 → trade remains
        ACCEPTED_PENDING_REVIEW.

        # difficulty: boundary_precision_check/veto_quorum_exact_threshold_at_50pct
        """
        bundle = setup_accepted_trade(team_count=10, veto_quorum_pct=50)
        league = bundle["league"]
        trade = bundle["trade"]
        for i in range(3):  # t3, t4, t5 → 3 vetoes
            voter = bundle["teams"][2 + i]
            cast_vote_as(trade["id"], voter, "VETO")
        latest = fetch_trade(league["id"], trade["id"])
        assert latest["status"] == "ACCEPTED_PENDING_REVIEW", \
            "PRD §3.7: 37 < 50 — threshold not crossed"

    def test_veto_at_threshold_crosses_to_vetoed(self, api):
        """PRD §3.7: "Equality with the quorum counts as crossed; strictly less does not. When the threshold is first crossed by a newly inserted VETO vote and the trade is still inside its review window (League.now_ts is strictly less than review_deadline_ts), the trade transitions immediately from ACCEPTED_PENDING_REVIEW to VETOED with no player or FAAB movement."

        Claim: with team_count=10 and veto_quorum_pct=50, 4 vetoes →
        (4*100)//8 = 50 >= 50 → trade transitions to VETOED. No
        player/FAAB movement.

        # difficulty: boundary_precision_check/veto_quorum_exact_threshold_at_50pct
        """
        bundle = setup_accepted_trade(team_count=10, veto_quorum_pct=50)
        league = bundle["league"]
        trade = bundle["trade"]
        p_send = bundle["p_send"]
        p_recv = bundle["p_recv"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        for i in range(4):  # 4 VETO votes
            voter = bundle["teams"][2 + i]
            cast_vote_as(trade["id"], voter, "VETO")
        latest = fetch_trade(league["id"], trade["id"])
        assert latest["status"] == "VETOED", \
            "PRD §3.7: 50 >= 50 — threshold crossed → VETOED"
        # Players still on original teams (no movement).
        t1_slots = list_roster_slots_for_team(league["id"], t1["id"])
        t2_slots = list_roster_slots_for_team(league["id"], t2["id"])
        assert any(s["player_id"] == p_send["id"] for s in t1_slots), \
            "PRD §3.7: VETOED branch has no player movement"
        assert any(s["player_id"] == p_recv["id"] for s in t2_slots), \
            "PRD §3.7: VETOED branch has no player movement"


# ===========================================================================
# Execution by clock — PRD §3.7
# ===========================================================================
class TestTradeExecution:
    def test_clock_past_deadline_executes_trade(self, api):
        """PRD §3.7: "When a clock advance crosses review_deadline_ts on a trade that is still in ACCEPTED_PENDING_REVIEW, the system evaluates the proposal. If the veto percentage is strictly below League.veto_quorum_pct (and League.now_ts is at or beyond review_deadline_ts), the trade transitions to EXECUTED and its side-effects fan out: each send_player_ids entry is moved to the counterparty's roster as BENCH with position_label null, each receive_player_ids entry is moved to the proposer's roster as BENCH with position_label null".

        Claim: clock advance past review_deadline_ts without veto
        transitions the trade to EXECUTED; the swapped player ends up
        on the counterparty's roster.
        """
        bundle = setup_accepted_trade(team_count=4, trade_review_hours=48)
        league = bundle["league"]
        trade = bundle["trade"]
        p_send = bundle["p_send"]
        t1 = bundle["teams"][0]
        t2 = bundle["teams"][1]
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=49))
        latest = fetch_trade(league["id"], trade["id"])
        assert latest["status"] == "EXECUTED", \
            "PRD §3.7: clock past review_deadline_ts with no veto → EXECUTED"
        t2_slots = list_roster_slots_for_team(league["id"], t2["id"])
        assert any(s["player_id"] == p_send["id"] for s in t2_slots), \
            "PRD §3.7: send_player_ids moved to counterparty (BENCH)"

    def test_faab_transfer_executes_atomically(self, api):
        """PRD §3.7: "any non-zero FAAB transfer is applied (the sending team's faab_balance_dollars is decremented and the receiving team's incremented by the matching amount, in whichever direction the non-zero value points)."

        Claim: with send_faab_dollars > 0, after EXECUTED the
        proposer's FAAB drops by exactly that amount and the
        counterparty's rises by exactly that amount.
        """
        bundle = setup_accepted_trade(team_count=4, send_faab_dollars=25)
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
        assert t1_after["faab_balance_dollars"] == t1_before["faab_balance_dollars"] - 25
        assert t2_after["faab_balance_dollars"] == t2_before["faab_balance_dollars"] + 25
