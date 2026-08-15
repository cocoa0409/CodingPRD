"""Auction clearing variants, tiered exchange fee, supply-path waterfall,
DSP billing, and the fee transparency report."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_auction_record,
    assert_dsp_billing_identity,
    assert_money_identity,
    assert_outcome,
    confirm_record,
    create_deal_for,
    create_package_for,
    create_partner,
    create_publisher,
    create_report,
    fill_auction,
    get_partner,
    list_records,
    make_bid,
    run_auction,
    setup_active_deal,
    submit_and_approve_deal,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]


def _two_variant_deals():
    """Two publishers with byte-identical approved deals differing only in
    auction_type: D_FP is FIRST_PRICE, D_SP is SECOND_PRICE; both floors
    1,000,000 (package base and deal floor alike)."""
    pub_fp = create_publisher("Pub FP", "pubfp.com")
    pub_sp = create_publisher("Pub SP", "pubsp.com")
    partner = create_partner()
    pkg_fp = create_package_for(pub_fp["id"], base_floor_cpm_micros=1000000)
    pkg_sp = create_package_for(pub_sp["id"], base_floor_cpm_micros=1000000)
    deal_fp = submit_and_approve_deal(
        create_deal_for(pub_fp["id"], pkg_fp["id"], partner["id"],
                        auction_type="FIRST_PRICE",
                        floor_cpm_micros=1000000)["id"], pub_fp["id"])
    deal_sp = submit_and_approve_deal(
        create_deal_for(pub_sp["id"], pkg_sp["id"], partner["id"],
                        auction_type="SECOND_PRICE",
                        floor_cpm_micros=1000000)["id"], pub_sp["id"])
    assert deal_fp["approved_floor_cpm_micros"] == 1000000
    assert deal_sp["approved_floor_cpm_micros"] == 1000000
    return pub_fp, pub_sp, deal_fp, deal_sp


def _variant_bids():
    return [make_bid(2000000, 1000, "x.com"), make_bid(1500000, 1000, "y.com")]


class TestClearingPriceVariants:
    def test_first_price_pays_the_winning_bid(self, api):
        """PRD §3.5: "a `FIRST_PRICE` deal clears at exactly the winning bid,
        recorded as `winning_bid_cpm_micros` and `clearing_cpm_micros` alike"
        PRD §3.5: "`gross_micros` is the `clearing_cpm_micros` multiplied by the
        winning bid's `impressions` and divided by 1,000, rounded half-up to
        integer micros."

        Design: Difficulty/dual_variant_calc/first_price_vs_second_price_clearing_divergence
        """
        pub_fp, _pub_sp, deal_fp, _deal_sp = _two_variant_deals()
        data = run_auction(pub_fp["id"], _variant_bids())
        assert_outcome(data, "FILL")
        record = data["auction_record"]
        assert_auction_record(record)
        assert record["deal_id"] == deal_fp["id"]
        assert record["auction_type"] == "FIRST_PRICE"
        assert record["winning_bid_cpm_micros"] == 2000000
        assert record["clearing_cpm_micros"] == 2000000, (
            "FIRST_PRICE pays what the winner bid")
        assert record["gross_micros"] == 2000000

    def test_second_price_pays_runner_up_plus_step(self, api):
        """PRD §3.5: "a `SECOND_PRICE` deal clears at the greater of the pinned
        floor and the second-highest eligible bid plus 1,000 micros — a
        tenth-of-a-cent step above the runner-up"

        Design: Difficulty/dual_variant_calc/first_price_vs_second_price_clearing_divergence
        """
        pub_fp, pub_sp, deal_fp, deal_sp = _two_variant_deals()
        fp_record = run_auction(pub_fp["id"], _variant_bids())["auction_record"]
        sp_record = run_auction(pub_sp["id"], _variant_bids())["auction_record"]
        assert sp_record["deal_id"] == deal_sp["id"]
        assert sp_record["winning_bid_cpm_micros"] == 2000000
        assert sp_record["clearing_cpm_micros"] == 1501000, (
            "SECOND_PRICE clears at max(pinned floor 1,000,000, runner-up "
            "1,500,000 + step 1,000)")
        assert sp_record["gross_micros"] == 1501000
        assert fp_record["gross_micros"] - sp_record["gross_micros"] == 499000, (
            "Identical bids diverge by exactly the variant delta")

    def test_second_price_sole_winner_clears_at_pinned_floor(self, api):
        """PRD §3.5: "and when the winner is the only eligible bid, the clearing
        price is simply the pinned floor."

        Design: Corner/calculations/second_price_sole_winner_clears_at_pinned_floor
        """
        sc = setup_active_deal(package_floor=1000000, deal_floor=1000000,
                               auction_type="SECOND_PRICE")
        assert sc["deal"]["approved_floor_cpm_micros"] == 1000000
        data = run_auction(sc["pub"]["id"], [make_bid(2500000, 1000, "a.com")])
        assert_outcome(data, "FILL")
        record = data["auction_record"]
        assert record["winning_bid_cpm_micros"] == 2500000
        assert record["clearing_cpm_micros"] == 1000000, (
            "A sole eligible winner pays the pinned floor, not its bid")
        assert record["gross_micros"] == 1000000


class TestExchangeFeeTiers:
    def test_tiered_exchange_fee_marginal_slabs(self, api):
        """PRD §3.5: "the first 5,000,000 micros — five dollars — are charged at
        1,500 basis points, any portion above that up to 20,000,000 micros is
        charged at 1,000 basis points, and any portion above 20,000,000 micros
        is charged at 500 basis points, with each slab individually rounded
        half-up and the rounded slabs summed into `exchange_fee_micros`."

        Design: Difficulty/combinatorial_formula/tiered_exchange_fee_marginal_slabs
        """
        sc = setup_active_deal()
        data = run_auction(sc["pub"]["id"], [make_bid(4200000, 5000, "big.com")])
        record = data["auction_record"]
        assert record["gross_micros"] == 21000000, (
            "4,200,000 CPM x 5000 imps / 1000")
        assert record["exchange_fee_micros"] == 2300000, (
            "Marginal slabs: 750,000 + 1,500,000 + 50,000 — not a flat rate")

    def test_tiered_fee_slabs_feed_publisher_net(self, api):
        """PRD §3.5: "`publisher_net_micros` is what is left — `gross_micros`
        minus `exchange_fee_micros` minus `supply_fee_micros`, exactly the final
        remainder."
        PRD §3.5: "the per-hop fees sum into `supply_fee_micros`, an empty chain
        charges nothing"

        Design: Difficulty/combinatorial_formula/tiered_exchange_fee_marginal_slabs
        """
        sc = setup_active_deal()
        record = run_auction(sc["pub"]["id"],
                             [make_bid(4200000, 5000, "big.com")])["auction_record"]
        assert record["supply_fee_micros"] == 0, "No supply chain: no supply fee"
        assert record["publisher_net_micros"] == 18700000
        assert_money_identity(record)

    def test_exchange_fee_tier1_cap_exact_boundary(self, api):
        """PRD §3.5: "the first 5,000,000 micros — five dollars — are charged at
        1,500 basis points, any portion above that up to 20,000,000 micros is
        charged at 1,000 basis points"

        Design: Corner/calculations/exchange_fee_tier1_cap_exact_boundary
        """
        sc = setup_active_deal()
        record = run_auction(sc["pub"]["id"],
                             [make_bid(5000000, 1000, "a.com")])["auction_record"]
        assert record["gross_micros"] == 5000000, "Exactly the slab-1 cap"
        assert record["exchange_fee_micros"] == 750000, (
            "15% of 5,000,000; the second slab requires gross strictly above "
            "the cap and contributes zero")


class TestSupplyPathWaterfall:
    def test_waterfall_per_hop_rounding_on_shrinking_remainder(self, api):
        """PRD §3.5: "The supply-path fee then walks the deal's package chain
        head-first by ascending `hop_index`, applied to what remains after the
        exchange fee: each hop's fee is the current remainder multiplied by that
        hop's `fee_bps` and divided by 10,000, rounded half-up, and the remainder
        shrinks by that fee before the next hop"

        Design: Difficulty/combinatorial_formula/supply_path_waterfall_per_hop_rounding
        """
        sc = setup_active_deal(package_floor=2000000, deal_floor=1500000,
                               auction_type="SECOND_PRICE",
                               supply_hops=(("ssp1.com", 1000), ("ssp2.com", 500)))
        assert sc["deal"]["approved_floor_cpm_micros"] == 2000000
        record = run_auction(sc["pub"]["id"], [
            make_bid(3000000, 2000, "a.com"),
            make_bid(2400000, 1000, "b.com"),
        ])["auction_record"]
        assert record["clearing_cpm_micros"] == 2401000, (
            "SECOND_PRICE: max(2,000,000, 2,400,000 + 1,000)")
        assert record["gross_micros"] == 4802000
        assert record["exchange_fee_micros"] == 720300, "Slab 1 only (<= 5M)"

    def test_waterfall_fee_sum_and_net(self, api):
        """PRD §3.5: "the per-hop fees sum into `supply_fee_micros`, an empty
        chain charges nothing, and `publisher_net_micros` is what is left —
        `gross_micros` minus `exchange_fee_micros` minus `supply_fee_micros`,
        exactly the final remainder."

        Design: Difficulty/combinatorial_formula/supply_path_waterfall_per_hop_rounding
        """
        sc = setup_active_deal(package_floor=2000000, deal_floor=1500000,
                               auction_type="SECOND_PRICE",
                               supply_hops=(("ssp1.com", 1000), ("ssp2.com", 500)))
        record = run_auction(sc["pub"]["id"], [
            make_bid(3000000, 2000, "a.com"),
            make_bid(2400000, 1000, "b.com"),
        ])["auction_record"]
        # remainder0 = 4,802,000 - 720,300 = 4,081,700
        # hop0: round_half_up(4,081,700 x 0.10) = 408,170; remainder1 3,673,530
        # hop1: round_half_up(3,673,530 x 0.05) = 183,677 (183,676.5 rounds up)
        assert record["supply_fee_micros"] == 591847, (
            "Per-hop rounding on the shrinking remainder: 408,170 + 183,677")
        assert record["publisher_net_micros"] == 3489853
        assert_money_identity(record)


class TestFloorBoundaryAndNoFill:
    def test_floor_boundary_no_fill_consumes_no_counters(self, api):
        """PRD §3.5: "Second, eligibility keeps only bids whose `bid_cpm_micros`
        is at least the deal's pinned `approved_floor_cpm_micros`"
        PRD §3.5: "A no-fill creates nothing, consumes nothing, and is never an
        error: no record, no counter movement, no throttle."

        Design: Corner/calculations/floor_boundary_no_fill_consumes_no_counters
        """
        sc = setup_active_deal(package_floor=2000000, deal_floor=2000000)
        assert sc["deal"]["approved_floor_cpm_micros"] == 2000000

        below = run_auction(sc["pub"]["id"], [make_bid(1999999, 1000, "a.com")])
        assert_outcome(below, "NO_FILL")
        partner = get_partner(sc["partner"]["id"])
        assert partner["current_second_auction_count"] == 0, (
            "One micro below the pinned floor: no counter movement")
        assert partner["spend_today_micros"] == 0
        assert partner["status"] == "ACTIVE", "A no-fill never throttles"

        at_floor = run_auction(sc["pub"]["id"], [make_bid(2000000, 1000, "a.com")])
        assert_outcome(at_floor, "FILL")
        assert at_floor["auction_record"]["clearing_cpm_micros"] == 2000000, (
            "A bid exactly at the pinned floor is eligible")

        records, meta = list_records(deal_id=sc["deal"]["id"])
        assert meta["total_count"] == 1, "Exactly one record exists after both calls"


class TestDspBillingAndTransparency:
    def test_dsp_billing_markup_feeds_report_views(self, api):
        """PRD §3.5: "`dsp_fee_micros` is `gross_micros` at a 1,000-basis-point
        markup rounded half-up, and `dsp_billed_micros` is the gross plus that
        fee."
        PRD §3.7: "The SSP set collects records whose `created_at` UTC date
        falls inside the window: their impressions sum into `ssp_impressions`
        and their gross into `ssp_spend_micros`. The DSP set collects records
        whose `dsp_confirmed_at` UTC date falls inside the window — confirmed
        records only: their impressions sum into `dsp_impressions` and their
        billed amounts into `dsp_billed_micros`."

        Design: Corner/calculations/dsp_billing_markup_feeds_report_views
        """
        sc = setup_active_deal()
        record = fill_auction(sc["pub"]["id"], bid_cpm_micros=2000000)
        assert record["gross_micros"] == 2000000
        assert record["dsp_fee_micros"] == 200000, "10% markup on gross"
        assert record["dsp_billed_micros"] == 2200000
        assert_dsp_billing_identity(record)
        confirm_record(record["id"])

        report = create_report(sc["deal"]["id"], "2026-08-01", "2026-08-02")
        assert report["ssp_spend_micros"] == 2000000, "SSP view sums gross"
        assert report["dsp_billed_micros"] == 2200000, (
            "DSP view sums billed (gross + markup) — the two views never "
            "reconcile to the same number")

    def test_fee_report_aggregates_two_records_with_chain(self, api):
        """PRD §3.8: "A per-package fee report answers with the package's
        declared `chain` ordered by ascending `hop_index`, its
        `non_voided_record_count` across all of its deals, and the summed
        `total_gross_micros`, `total_exchange_fee_micros`,
        `total_supply_fee_micros`, and `total_publisher_net_micros` over those
        records"

        Design: Corner/calculations/fee_report_aggregates_two_records_with_chain
        """
        sc = setup_active_deal(supply_hops=(("ssp1.com", 1000),))
        fill_auction(sc["pub"]["id"])
        fill_auction(sc["pub"]["id"])

        report = validate_success(api.get_package_fee_report(sc["pkg"]["id"], ADMIN))
        assert report["package_id"] == sc["pkg"]["id"]
        assert report["non_voided_record_count"] == 2
        # Per record: gross 1,000,000; fee 150,000; hop fee
        # round_half_up(850,000 x 0.10) = 85,000; net 765,000.
        assert report["total_gross_micros"] == 2000000
        assert report["total_exchange_fee_micros"] == 300000
        assert report["total_supply_fee_micros"] == 170000
        assert report["total_publisher_net_micros"] == 1530000
        assert len(report["chain"]) == 1
        assert report["chain"][0]["hop_index"] == 0, (
            "The chain is emitted in ascending hop_index order")
