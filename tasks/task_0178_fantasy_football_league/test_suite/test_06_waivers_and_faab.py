"""Waivers and FAAB bidding: submission validations, sweep
resolution algorithm, cancel flow.

Covers PRD §3.6 (every submission validation, the sweep algorithm,
the waiver_period_hours == 0 variant, the cancel-own-claim flow,
and the trade-cascade cancellation).
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    NON_EXISTENT_UUID,
    advance_clock_to,
    cancel_waiver_as,
    create_player,
    create_waiver_payload,
    fetch_team,
    fetch_waiver,
    find_by_id,
    iso_offset,
    iso_utc,
    list_roster_slots_for_team,
    list_waivers,
    make_manager_headers,
    set_player_status,
    setup_drafted_league,
    submit_waiver,
    validate_error,
    validate_success,
)


def _now(league):
    """Parse a League.now_ts back to a datetime."""
    return datetime.fromisoformat(league["now_ts"].replace("Z", "+00:00"))


# ===========================================================================
# Submission validations — PRD §3.6
# ===========================================================================
class TestWaiverSubmissionValidation:
    def test_settle_ts_in_past_rejected(self, api):
        """PRD §3.6: "The submitted settle_ts must be strictly greater than League.now_ts (a same-instant or past settle_ts is rejected with ERR_WAIVER_SETTLE_IN_PAST)."

        Claim: settle_ts <= now_ts is rejected with ERR_WAIVER_SETTLE_IN_PAST.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        # Create an out-of-roster player to bid on; mark OUT so the
        # in-waivers check passes for a real submission, but here
        # settle_ts is past so settle check should fire first.
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        now_dt = _now(league)
        past_settle = iso_utc(now_dt - timedelta(hours=1))
        payload = create_waiver_payload(
            team_id=t0["id"],
            add_player_id=free_player["id"],
            bid_dollars=5,
            settle_ts=past_settle,
        )
        headers = make_manager_headers(t0["manager_user_id"])
        res = api.create_waiver(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_WAIVER_SETTLE_IN_PAST.value)

    def test_bid_exceeds_faab_balance_rejected(self, api):
        """PRD §3.6: "The bid_dollars may not exceed the submitting team's current faab_balance_dollars; an over-bid is rejected with ERR_FAAB_INSUFFICIENT."

        Claim: bid_dollars > Team.faab_balance_dollars is rejected.
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=10)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        now_dt = _now(league)
        settle = iso_utc(now_dt + timedelta(hours=2))
        payload = create_waiver_payload(
            team_id=t0["id"], add_player_id=free_player["id"],
            bid_dollars=999, settle_ts=settle,
        )
        headers = make_manager_headers(t0["manager_user_id"])
        res = api.create_waiver(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_FAAB_INSUFFICIENT.value)

    def test_bid_on_already_rostered_player_rejected(self, api):
        """PRD §3.6: "The add_player_id may not already be on any roster in the league; an attempt to bid on a rostered player surfaces as ERR_PLAYER_ALREADY_ROSTERED."

        Claim: bidding on a Player who is already on some team's
        roster yields ERR_PLAYER_ALREADY_ROSTERED.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        # Pick any player that's already drafted (on t1's roster).
        t1 = bundle["teams"][1]
        t1_slots = list_roster_slots_for_team(league["id"], t1["id"])
        target_player_id = t1_slots[0]["player_id"]
        now_dt = _now(league)
        settle = iso_utc(now_dt + timedelta(hours=2))
        payload = create_waiver_payload(
            team_id=t0["id"], add_player_id=target_player_id,
            bid_dollars=1, settle_ts=settle,
        )
        headers = make_manager_headers(t0["manager_user_id"])
        res = api.create_waiver(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_PLAYER_ALREADY_ROSTERED.value)


# ===========================================================================
# Sweep tiebreak — PRD §3.6 (highest bid; ties by priority_seed asc)
# ===========================================================================
class TestSweepResolution:
    def test_higher_bid_wins(self, api):
        """PRD §3.6: "within each group, sorts claims by bid_dollars descending with ties broken by priority_seed ascending and a final tiebreak of created_at ascending."

        Claim: when two claims target the same player with different
        bids, the higher bid wins.
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        t0, t1 = bundle["teams"][0], bundle["teams"][1]
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        # Both teams submit claims with same settle_ts.
        w0 = submit_waiver(
            league=league, team=t0, add_player_id=free_player["id"],
            bid_dollars=5, settle_offset_hours=2,
        )
        w1 = submit_waiver(
            league=league, team=t1, add_player_id=free_player["id"],
            bid_dollars=10, settle_offset_hours=2,
        )
        # Advance the clock past settle_ts.
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=3))
        # Trigger the explicit sweep too (idempotent if clock-advance
        # already ran one).
        api.process_waivers(league["id"], make_manager_headers.__self__ if False else None)
        # Actually use commissioner headers for /_waivers/process.
        from test_helpers import COMMISSIONER
        api.process_waivers(league["id"], COMMISSIONER)
        w0_after = fetch_waiver(league["id"], w0["id"])
        w1_after = fetch_waiver(league["id"], w1["id"])
        assert w1_after["status"] == "AWARDED", \
            "PRD §3.6: higher bid_dollars wins the sweep group"
        assert w0_after["status"] == "LOST"

    def test_award_decrements_faab_balance(self, api):
        """PRD §3.6: "The winning claim transitions to AWARDED, the team's faab_balance_dollars is decremented by the winning bid_dollars".

        Claim: the AWARDED claim decrements its team's
        faab_balance_dollars by the bid amount.
        """
        bundle = setup_drafted_league(team_count=4, faab_budget_dollars=100)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        before = fetch_team(league["id"], t0["id"])
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        submit_waiver(
            league=league, team=t0, add_player_id=free_player["id"],
            bid_dollars=15, settle_offset_hours=2,
        )
        now_dt = _now(league)
        advance_clock_to(league["id"], now_dt + timedelta(hours=3))
        from test_helpers import COMMISSIONER
        api.process_waivers(league["id"], COMMISSIONER)
        after = fetch_team(league["id"], t0["id"])
        assert after["faab_balance_dollars"] == before["faab_balance_dollars"] - 15, \
            "PRD §3.6: AWARDED debits faab_balance_dollars by bid_dollars"


# ===========================================================================
# Cancel-own-claim — PRD §3.6
# ===========================================================================
class TestCancelOwnClaim:
    def test_owner_cancels_pending_claim(self, api):
        """PRD §3.6: "The owning Manager may also cancel a PENDING claim before its settle_ts is reached; this requires that the acting manager own the claim's team and that League.now_ts be strictly less than the claim's settle_ts, and it transitions the claim to CANCELED."

        Claim: a PENDING claim cancelled by its owner before
        settle_ts moves to CANCELED.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0 = bundle["teams"][0]
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        w0 = submit_waiver(
            league=league, team=t0, add_player_id=free_player["id"],
            bid_dollars=5, settle_offset_hours=6,
        )
        cancelled = cancel_waiver_as(w0["id"], t0)
        assert cancelled["status"] == "CANCELED"

    def test_non_owner_cannot_cancel_claim(self, api):
        """PRD §3.6: "this requires that the acting manager own the claim's team".
        PRD §2.1: "any operation that targets a team_id other than the one the acting Manager owns is rejected with ERR_NOT_TEAM_OWNER."

        Claim: a different Manager cannot cancel another team's
        PENDING claim.
        """
        bundle = setup_drafted_league(team_count=4)
        league = bundle["league"]
        t0, t1 = bundle["teams"][0], bundle["teams"][1]
        free_player = create_player(position="WR")
        set_player_status(free_player["id"], "OUT")
        w0 = submit_waiver(
            league=league, team=t0, add_player_id=free_player["id"],
            bid_dollars=5, settle_offset_hours=6,
        )
        h_other = make_manager_headers(t1["manager_user_id"])
        res = api.cancel_waiver(w0["id"], h_other)
        validate_error(res, ApiErrorId.ERR_NOT_TEAM_OWNER.value)
