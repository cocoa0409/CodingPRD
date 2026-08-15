"""Demand-side capacity gates: per-second QPS throttle, daily budget cap,
clock-driven reactivation, and PG commitment exhaustion."""
from test_helpers import (
    assert_outcome,
    create_deal_for,
    create_package_for,
    create_partner,
    create_publisher,
    fill_auction,
    get_deal,
    get_partner,
    make_bid,
    run_auction,
    set_clock,
    setup_active_deal,
    submit_and_approve_deal,
)


def _qps_scenario(max_qps=1, daily_cap=100000000):
    """One publisher, one package (base floor 500,000), and one partner with
    two approved FIRST_PRICE deals: D_LO (floor 1,000,000 — the lowest
    approved floor, hence candidate k=1) and D_HI (floor 2,000,000)."""
    pub = create_publisher()
    partner = create_partner(max_qps=max_qps, daily_cap_micros=daily_cap)
    pkg = create_package_for(pub["id"])
    d_lo = submit_and_approve_deal(
        create_deal_for(pub["id"], pkg["id"], partner["id"],
                        floor_cpm_micros=1000000)["id"], pub["id"])
    d_hi = submit_and_approve_deal(
        create_deal_for(pub["id"], pkg["id"], partner["id"],
                        floor_cpm_micros=2000000)["id"], pub["id"])
    assert d_lo["approved_floor_cpm_micros"] == 1000000
    assert d_hi["approved_floor_cpm_micros"] == 2000000
    return pub, partner, d_lo, d_hi


class TestQpsBoundary:
    def test_position_at_max_qps_allowed_next_candidate_throttled(self, api):
        """PRD §3.5: "the k-th candidate in that order participates only if the
        partner's `current_second_auction_count` plus k is at most its
        `max_qps`. A position exactly equal to `max_qps` is allowed; one beyond
        it is throttled."
        PRD §3.5: "a `throttled_deal_count` reporting how many candidate deals
        were excluded from this request purely by the per-second capacity gate."

        Design: Difficulty/boundary_precision_check/qps_position_at_max_allowed_next_throttled
        """
        pub, partner, d_lo, d_hi = _qps_scenario(max_qps=1)
        data = run_auction(pub["id"], [make_bid(3000000, 1000, "a.com")])
        assert_outcome(data, "FILL")
        record = data["auction_record"]
        # Candidates are walked lowest approved floor first: D_LO is position 1
        # (== max_qps, allowed) and D_HI is position 2 (== max_qps + 1,
        # excluded), so the admitted D_LO fills at FIRST_PRICE.
        assert record["deal_id"] == d_lo["id"]
        assert record["clearing_cpm_micros"] == 3000000
        assert data["throttled_deal_count"] == 1, (
            "Exactly one candidate (D_HI at would-be position 2) was excluded "
            "by the per-second gate")

    def test_qps_exclusion_flips_partner_to_throttled_after_auction(self, api):
        """PRD §3.5: "If any candidate is excluded purely by the per-second
        gate, the partner transitions to `THROTTLED` for capacity reasons after
        the auction completes; the current auction still runs with the admitted
        candidates."
        PRD §3.5: "The partner's `current_second_auction_count` increments by
        one, and its `spend_today_micros` and `lifetime_spend_micros` each grow
        by the record's `gross_micros`."

        Design: Difficulty/boundary_precision_check/qps_position_at_max_allowed_next_throttled
        """
        pub, partner, d_lo, d_hi = _qps_scenario(max_qps=1)
        run_auction(pub["id"], [make_bid(3000000, 1000, "a.com")])
        after = get_partner(partner["id"])
        assert after["status"] == "THROTTLED", (
            "The QPS-excluded candidate flips the partner after the auction")
        assert after["current_second_auction_count"] == 1, (
            "The admitted fill still increments the per-second counter")
        assert after["spend_today_micros"] == 3000000
        assert after["lifetime_spend_micros"] == 3000000


class TestDailyCapBoundary:
    def test_daily_cap_exactly_reached_blocks_next_auction(self, api):
        """PRD §3.5: "The budget gate is evaluated once per request per partner:
        if the partner's `spend_today_micros` has already reached its
        `daily_cap_micros` — exactly at the cap blocks, one micro below it does
        not — none of that partner's candidates participate, and the partner
        transitions from `ACTIVE` to `THROTTLED` for budget reasons."

        Design: Corner/calculations/daily_cap_exactly_reached_blocks_next_auction
        """
        sc = setup_active_deal(daily_cap_micros=1000000)
        first = run_auction(sc["pub"]["id"], [make_bid(1000000, 1000, "a.com")])
        assert_outcome(first, "FILL")
        mid = get_partner(sc["partner"]["id"])
        assert mid["spend_today_micros"] == 1000000, (
            "First fill accrues gross exactly to the cap")

        second = run_auction(sc["pub"]["id"], [make_bid(1000000, 1000, "a.com")])
        assert_outcome(second, "NO_FILL")
        after = get_partner(sc["partner"]["id"])
        assert after["spend_today_micros"] == 1000000
        assert after["status"] == "THROTTLED", (
            "spend == cap exactly blocks all candidacy (>= boundary)")


class TestClockRollover:
    def test_clock_rollover_resets_qps_and_auto_reactivates(self, api):
        """PRD §2.4: "When the new time enters a later UTC second, every demand
        partner's `current_second_auction_count` resets to zero, and any partner
        sitting in `THROTTLED` is automatically reactivated to `ACTIVE` provided
        the new time is in a later UTC second than the one in which it was
        throttled and its `spend_today_micros`, recomputed for the new UTC date,
        is below its `daily_cap_micros`."

        Design: Corner/cross_cutting/clock_rollover_resets_qps_and_auto_reactivates
        """
        pub, partner, d_lo, d_hi = _qps_scenario(max_qps=1)
        first = run_auction(pub["id"], [make_bid(3000000, 1000, "a.com")])
        assert_outcome(first, "FILL")
        assert get_partner(partner["id"])["status"] == "THROTTLED"

        set_clock("2026-08-01T00:00:01Z")
        revived = get_partner(partner["id"])
        assert revived["status"] == "ACTIVE", (
            "Later second and spend 3,000,000 < cap: auto-reactivation fires")
        assert revived["current_second_auction_count"] == 0, (
            "The per-second counter resets on second rollover")

        second = run_auction(pub["id"], [make_bid(3000000, 1000, "a.com")])
        assert_outcome(second, "FILL")
        assert second["auction_record"]["deal_id"] == d_lo["id"]
        assert second["throttled_deal_count"] == 1, (
            "D_HI throttles again in the new second")
        assert get_partner(partner["id"])["status"] == "THROTTLED", (
            "Throttle is re-evaluated per second, not sticky")


class TestPgCommitmentExhaustion:
    def test_pg_commitment_exhaustion_removes_deal_from_candidacy(self, api):
        """PRD §3.5: "A deal is eligible only when all of the following hold:
        ... a `PROGRAMMATIC_GUARANTEED` deal still has
        `remaining_committed_impressions` greater than zero"
        PRD §3.5: "if no deal fills, the outcome is a no-fill."

        Design: Corner/calculations/pg_commitment_exhaustion_removes_deal_from_candidacy
        """
        sc = setup_active_deal(deal_type="PROGRAMMATIC_GUARANTEED",
                               committed_impressions=1000)
        first = run_auction(sc["pub"]["id"], [make_bid(1000000, 1000, "a.com")])
        assert_outcome(first, "FILL")
        deal = get_deal(sc["deal"]["id"])
        assert deal["delivered_impressions"] == 1000
        assert deal["remaining_committed_impressions"] == 0, (
            "Delivery of exactly the commitment exhausts the remainder")

        second = run_auction(sc["pub"]["id"], [make_bid(1000000, 1000, "a.com")])
        assert_outcome(second, "NO_FILL")
        assert get_deal(sc["deal"]["id"])["status"] == "ACTIVE", (
            "The deal is still ACTIVE and in flight — only the exhausted "
            "commitment excludes it")
