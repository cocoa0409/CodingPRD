"""Bid submission, withdrawal, the 24-hour cutoff, and the awarding sweep.

Covers PRD §3.2 (Bid lifecycle) and §3.3 (Awarding Sweep, both variants).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    BID_CUTOFF_HOURS_BEFORE_START,
    BidStatus,
    PairingStatus,
    add_hours_iso,
    award_bid_window,
    build_pairing_with_one_duty_period,
    create_bid_payload,
    create_crew_member,
    crew_role_headers,
    get_pairing,
    iso_from_dt,
    list_assignments,
    open_bidding,
    pilot_headers_for,
    publish_and_open_bidding,
    publish_pairing,
    setup_pairing_admin_assigned,
    setup_pairing_in_bidding,
    submit_bid,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestBidSubmission:

    def test_submit_bid_on_bidding_open_pairing(self, api):
        """PRD §3.2: "A Pilot or FlightAttendant submits a Bid against a
        BIDDING_OPEN pairing by sending the target pairing_id, a
        preference_rank indicating the bidder's ordering within their
        own bid set for this window (1 being most preferred), and the
        bid_window_id. The bid is born SUBMITTED."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        resp = api.create_bid(
            create_bid_payload(pairing["id"], bw, preference_rank=1),
            crew_role_headers(pilot),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == BidStatus.SUBMITTED.value
        assert data["preference_rank"] == 1
        assert data["crew_member_id"] == pilot["id"]
        assert data["pairing_id"] == pairing["id"]
        assert data["bid_window_id"] == bw

    def test_duplicate_preference_rank_within_window_rejected(self, api):
        """PRD §3.2: "preference_rank must be strictly positive and
        unique within the pair (crew_member_id, bid_window_id); a
        duplicate is rejected with ERR_DUPLICATE_BID_PREFERENCE."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Two distinct pairings sharing one bid window.
        p1, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        p2, _ = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
            bid_window_id=bw,
        )
        submit_bid(pilot, p1["id"], bw, preference_rank=1)
        # Reuse preference_rank=1 under same window.
        resp = api.create_bid(
            create_bid_payload(p2["id"], bw, preference_rank=1),
            crew_role_headers(pilot),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BID_PREFERENCE.value)

    def test_bid_within_24h_of_start_rejected(self, api):
        """PRD §3.2: "Submitting a bid less than 24 hours before
        Pairing.start_at is rejected with ERR_BID_TOO_LATE (the
        inclusive 24-hour cutoff is enforced strictly: a start_at minus
        24 hours that exactly equals now is still permitted; anything
        later is rejected)."

        # difficulty: boundary_precision_check/crew_rest_exactly_600_minutes
        Test the "less than 24h" side: start_at is +23h from now.
        """
        # Build a pairing with start_at +25h (passes open-bidding's 24h
        # lead) but then advance the server clock to +1h before start_at
        # → at submit time, start_at - now = 24h ... we need <24h so the
        # cutoff fires. Use +23.5h from creation time so start - now < 24h.
        # Server-side clock equals wall time for this test (no /_clock
        # advance). Use start_at = now + 23h.
        in_23h = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=23),
        )
        # open_bidding requires +24h → must first get to BIDDING_OPEN by
        # using +25h then advancing clock. Simpler: build with +25h, open
        # bidding (passes), then use /_clock/advance to move +2h forward.
        in_25h = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(hours=25),
        )
        from test_helpers import advance_clock_to
        pairing, _, _ = build_pairing_with_one_duty_period(
            start_at=in_25h,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        from test_helpers import random_bid_window_id
        bw = random_bid_window_id()
        open_bidding(pairing["id"], bid_window_id=bw)

        # Move clock forward by 2 hours → now - start_at = -23h, i.e.,
        # start - now = 23h < 24h.
        target = iso_from_dt(datetime.now(timezone.utc) + timedelta(hours=2))
        advance_clock_to(target)

        pilot = create_crew_member(rank="CAPTAIN")
        resp = api.create_bid(
            create_bid_payload(pairing["id"], bw, preference_rank=1),
            crew_role_headers(pilot),
        )
        validate_error(resp, ApiErrorId.ERR_BID_TOO_LATE.value)


class TestBidWithdrawal:

    def test_owner_can_withdraw_their_submitted_bid(self, api):
        """PRD §3.2: "A bidder may withdraw their own SUBMITTED bid
        while the pairing remains BIDDING_OPEN, taking the bid from
        SUBMITTED to WITHDRAWN."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        bid = submit_bid(pilot, pairing["id"], bw, preference_rank=1)
        resp = api.delete_bid(bid["id"], crew_role_headers(pilot))
        assert resp.status_code == 204, (
            f"PRD §4 DELETE /bids/{{id}} returns 204; got {resp.status_code}"
        )


class TestAwardingSweep:

    def test_seniority_first_awards_lowest_seniority_number(self, api):
        """PRD §3.3: "The default seniority_first variant ranks
        candidates by union_seniority_number ascending alone, then
        applies the FAA duty/rest check."

        # difficulty: dual_variant_calc/bid_award_seniority_vs_load_balanced
        First half of the dual-variant pair — seniority_first awards
        the lower union_seniority_number. The load_balanced counterpart
        is `test_load_balanced_awards_lowest_cumulative_block`.
        """
        # Pilot A is senior (seniority=1); Pilot B is junior (seniority=100).
        senior = create_crew_member(
            rank="CAPTAIN", union_seniority_number=1,
        )
        junior = create_crew_member(
            rank="CAPTAIN", union_seniority_number=100,
        )
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        submit_bid(senior, pairing["id"], bw, preference_rank=1)
        submit_bid(junior, pairing["id"], bw, preference_rank=1)
        award_bid_window(bw)
        # Expect one Assignment created for the senior pilot.
        assignments = list_assignments(params={"limit": 100})
        relevant = [
            a for a in assignments
            if a.get("pairing_id") == pairing["id"]
            and a.get("source") == "BID_AWARD"
        ]
        assert len(relevant) == 1
        assert relevant[0]["crew_member_id"] == senior["id"], (
            "PRD §3.3 seniority_first awards the lowest "
            "union_seniority_number first."
        )

    def test_load_balanced_awards_lowest_cumulative_block(self, api):
        """PRD §3.3: "The load_balanced variant — selected when the
        pairing's required_rank_composition object carries the flag
        mode: 'LOAD_BALANCED' — instead ranks candidates first by
        cumulative_block_minutes_30d ascending (least-used first), with
        union_seniority_number ascending as the tie-break, before
        applying the same FAA check."

        # difficulty: dual_variant_calc/bid_award_seniority_vs_load_balanced
        """
        # Senior (A) has high cumulative_block_minutes_30d; junior (B)
        # has 0. Under LOAD_BALANCED, B wins.
        from test_helpers import raise_cumulative_block_30d
        senior = create_crew_member(
            rank="CAPTAIN", union_seniority_number=1,
        )
        # Push senior's cumulative_block to ~5000 minutes via admin
        # assignments on prior pairings.
        senior = raise_cumulative_block_30d(senior, target_minutes=5000)
        junior = create_crew_member(
            rank="CAPTAIN", union_seniority_number=100,
        )

        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1, "mode": "LOAD_BALANCED"},
        )
        submit_bid(senior, pairing["id"], bw, preference_rank=1)
        submit_bid(junior, pairing["id"], bw, preference_rank=1)
        award_bid_window(bw)
        assignments = list_assignments(params={"limit": 100})
        relevant = [
            a for a in assignments
            if a.get("pairing_id") == pairing["id"]
            and a.get("source") == "BID_AWARD"
        ]
        assert len(relevant) == 1
        assert relevant[0]["crew_member_id"] == junior["id"], (
            "PRD §3.3 load_balanced: least-used (lowest "
            "cumulative_block_minutes_30d) wins."
        )

    def test_second_award_sweep_rejected(self, api):
        """PRD §3.3: "a second sweep on the same window finds no
        BIDDING_OPEN pairings and is rejected at the window level with
        ERR_BID_WINDOW_ALREADY_AWARDED."
        """
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        submit_bid(pilot, pairing["id"], bw, preference_rank=1)
        award_bid_window(bw)
        # Second sweep on same window.
        from test_helpers import scheduler_headers as _sch
        resp = api.award_bid_window(bw, _sch())
        validate_error(
            resp, ApiErrorId.ERR_BID_WINDOW_ALREADY_AWARDED.value,
        )

    def test_chronological_order_disqualifies_later_pairing_via_30d_cap(
        self, api,
    ):
        """PRD §3.3: "Pairings in the sweep are processed in a pinned
        chronological order: first by ascending Pairing.start_at, with
        ascending Pairing.created_at as the secondary tie-break. The
        order matters because awarding an earlier pairing to a candidate
        increments that candidate's cumulative counters, which can
        disqualify them on a later pairing within the same sweep."

        # difficulty: combinatorial_formula/bid_award_chronological_dependency
        """
        # Pilot M has cumulative_block ~= 5000 going in; two pairings,
        # each 600min, in same window.
        from test_helpers import raise_cumulative_block_30d
        pilot = create_crew_member(rank="CAPTAIN", union_seniority_number=1)
        pilot = raise_cumulative_block_30d(pilot, target_minutes=5000)

        # P_early starts +30d (within rolling 30d window) and is small
        # enough to fit under cap; P_late is later.
        start_early = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=2),
        )
        start_late = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=10),
        )
        from test_helpers import (
            build_pairing_with_one_duty_period,
            publish_pairing,
            open_bidding,
            random_bid_window_id,
        )
        bw = random_bid_window_id()
        p_early, _, _ = build_pairing_with_one_duty_period(
            start_at=start_early,
            revenue_block_minutes=600, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        p_late, _, _ = build_pairing_with_one_duty_period(
            start_at=start_late,
            revenue_block_minutes=600, duty_minutes=720,
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(p_early["id"])
        publish_pairing(p_late["id"])
        open_bidding(p_early["id"], bid_window_id=bw)
        open_bidding(p_late["id"], bid_window_id=bw)
        submit_bid(pilot, p_early["id"], bw, preference_rank=1)
        submit_bid(pilot, p_late["id"], bw, preference_rank=2)
        award_bid_window(bw)

        # Pilot earned 600 on P_early -> cumulative 5600; P_late would
        # push to 6200, breaching MAX_BLOCK_MINUTES_30D=6000 → no award.
        assignments = list_assignments(params={"limit": 100})
        early_a = [
            a for a in assignments
            if a.get("pairing_id") == p_early["id"]
            and a.get("crew_member_id") == pilot["id"]
        ]
        late_a = [
            a for a in assignments
            if a.get("pairing_id") == p_late["id"]
            and a.get("crew_member_id") == pilot["id"]
        ]
        assert len(early_a) == 1, (
            "PRD §3.3 P_early should award since 5000+600 <= 6000."
        )
        assert len(late_a) == 0, (
            "PRD §3.3 chronological order: P_late should be skipped "
            "because cumulative now 5600+600=6200 > 6000."
        )
