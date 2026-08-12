"""Difficulty: combinatorial_formula — tier modes, pinned rounding order, percentile population."""
from test_helpers import (
    TEST_USERS,
    api_client,
    finalize_settlement,
    get_review_for_assignment,
    make_vendor_spec,
    move_to_settlement_phase,
    open_settlements,
    reconcile_all,
    reconcile_settlement,
    report_sales,
    setup_active_assignment,
    setup_live_multi,
    create_settlement,
    report_sale,
    validate_success,
)

VM = TEST_USERS["vendor_manager_headers"]
FIN1 = TEST_USERS["finance_headers"]


def _setup_tier_pair():
    """Two ACTIVE REVENUE_SHARE 2000bp assignments — C MARGINAL, D WHOLE_TIER —
    each with one 600000-cent REPORTED sale; settlements created."""
    specs = [
        make_vendor_spec("Cider Co", "BEVERAGE_NA", fee_model="REVENUE_SHARE",
                         revenue_share_pct_bp=2000, tier_mode="MARGINAL"),
        make_vendor_spec("Donut Co", "DESSERT", fee_model="REVENUE_SHARE",
                         revenue_share_pct_bp=2000, tier_mode="WHOLE_TIER"),
    ]
    scen = setup_live_multi(specs, name="Tier Fest", zone_power=200)
    report_sales(scen, [[{"amount_cents": 600000, "key": "tc1"}],
                        [{"amount_cents": 600000, "key": "td1"}]])
    open_settlements(scen)
    return scen


class TestTierModeNonLinear:
    def test_marginal_mode_splits_across_tier_ladder(self, api):
        """PRD §3.6: "Under `MARGINAL` tier mode, each transaction's amount is
        split into portions according to where it lands on the running-gross
        ladder, each portion's share is that portion multiplied by its tier's
        effective rate and divided by 10,000, rounded half-up to whole cents, and
        the transaction's share is the sum of its tier portions."

        Design: Difficulty/combinatorial_formula/tiered_marginal_vs_whole_tier_nonlinear
        """
        scen = _setup_tier_pair()
        rec_c = reconcile_settlement(scen["settlements"][0]["id"])
        assert rec_c["provisional_gross_cents"] == 600000
        # 500000 @ 2000bp (100000) + 100000 @ 3000bp (30000)
        assert rec_c["provisional_share_cents"] == 130000
        assert rec_c["provisional_payout_cents"] == 470000

    def test_whole_tier_mode_charges_single_selected_multiplier(self, api):
        """PRD §3.6: "Under `WHOLE_TIER` mode, a single multiplier is chosen once
        per transaction — the tier in which the running gross sits after the
        transaction is added (first tier when the new running gross is at most
        500,000 cents, second when at most 2,000,000, otherwise third) — and the
        whole transaction amount is charged at that tier's effective rate."

        Design: Difficulty/combinatorial_formula/tiered_marginal_vs_whole_tier_nonlinear
        """
        scen = _setup_tier_pair()
        rec_c = reconcile_settlement(scen["settlements"][0]["id"])
        rec_d = reconcile_settlement(scen["settlements"][1]["id"])
        assert rec_d["provisional_gross_cents"] == 600000, "identical inputs"
        # post-add running gross 600000 > T1 -> tier 2 (1.5x): 600000 @ 3000bp
        assert rec_d["provisional_share_cents"] == 180000
        assert rec_d["provisional_payout_cents"] == 420000
        assert rec_c["provisional_share_cents"] != rec_d["provisional_share_cents"], (
            "tier_mode alone moves the share by 50000 cents"
        )


class TestPerLineRoundingPinned:
    def test_three_105_cent_sales_round_per_line_to_33(self, api):
        """PRD §3.6: "With amounts of 105 cents each, per-line rounding yields 11
        cents per transaction for a total of 33 cents, whereas the rejected
        sum-then-round order would yield 32 — the pinned order is observable and
        must be reproduced exactly."

        Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned
        """
        scen = setup_active_assignment(
            name="Rounding Fest", fee_model="REVENUE_SHARE",
            terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
            power_needed_amps=10,
        )
        asg_id = scen["assignment"]["id"]
        for i, at in enumerate(["2026-07-10T14:00:00Z", "2026-07-10T14:05:00Z", "2026-07-10T14:10:00Z"]):
            report_sale(asg_id, scen["vendor"], 105, f"r{i + 1}", occurred_at=at)
        stl = create_settlement(asg_id)
        rec = reconcile_settlement(stl["id"])
        assert rec["provisional_gross_cents"] == 315
        assert rec["provisional_share_cents"] == 33, "pinned per-transaction rounding: 11 + 11 + 11"
        assert rec["provisional_share_cents"] != 32, "sum-then-round order is rejected"
        assert rec["provisional_payout_cents"] == 282

    def test_three_101_cent_sales_round_per_line_to_30(self, api):
        """PRD §3.6: "Consider a pinned rate of 1,000 basis points (ten percent)
        under `MARGINAL` with three transactions of 101 cents each, all within
        the first tier: each transaction's share is 10.1 cents rounded half-up to
        10, and the festival share is 30 cents."

        Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned
        """
        scen = setup_active_assignment(
            name="Rounding Fest B", fee_model="REVENUE_SHARE",
            terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
            power_needed_amps=10,
        )
        asg_id = scen["assignment"]["id"]
        for i, at in enumerate(["2026-07-10T14:00:00Z", "2026-07-10T14:05:00Z", "2026-07-10T14:10:00Z"]):
            report_sale(asg_id, scen["vendor"], 101, f"r{i + 1}", occurred_at=at)
        stl = create_settlement(asg_id)
        rec = reconcile_settlement(stl["id"])
        assert rec["provisional_gross_cents"] == 303
        assert rec["provisional_share_cents"] == 30, "10 + 10 + 10 per the pinned example"
        assert rec["provisional_payout_cents"] == 273


def _setup_percentile_trio():
    """Festival (cap 1) with three ACTIVE FLAT_FEE 50000 assignments F/G/H
    (grosses 100000/200000/300000); settlements reconciled; festival in
    SETTLEMENT; F and G finalized. H's settlement left RECONCILING."""
    specs = [
        make_vendor_spec("Falafel F", "FOOD_HOT", flat_fee_cents=50000, power_draw_amps=30),
        make_vendor_spec("Gelato G", "DESSERT", flat_fee_cents=50000, power_draw_amps=30),
        make_vendor_spec("Hotdog H", "MERCHANDISE", flat_fee_cents=50000, power_draw_amps=30),
    ]
    scen = setup_live_multi(specs, name="Percentile Fest", cap=1, zone_power=300, zone_water=3)
    report_sales(scen, [[{"amount_cents": 100000, "key": "pf1"}],
                        [{"amount_cents": 200000, "key": "pg1"}],
                        [{"amount_cents": 300000, "key": "ph1"}]])
    open_settlements(scen)
    reconcile_all(scen)
    move_to_settlement_phase(scen)
    finalize_settlement(scen["settlements"][0]["id"])  # F
    finalize_settlement(scen["settlements"][1]["id"])  # G
    return scen


class TestPercentilePopulationPinned:
    def test_population_fixed_at_compute_time_early_vs_late(self, api):
        """PRD §3.8: "the population is every assignment of the same festival
        whose settlement is in `FINALIZED` or `PAID` at compute time, the scored
        assignment included".
        PRD §3.8: "Because every peer's settlement is already final, the
        population grosses are simply read — no recursion into scoring occurs."

        Design: Difficulty/combinatorial_formula/percentile_population_fixed_at_compute_time
        """
        scen = _setup_percentile_trio()
        rev_g = get_review_for_assignment(scen["assignments"][1]["id"])
        scored_g = validate_success(api.compute_score(rev_g["id"], VM))
        assert scored_g["sales_percentile"] == 50, "population {F,G} (N=2): one peer below"
        assert scored_g["official_score"] == 80
        assert scored_g["status"] == "SCORED"

        finalize_settlement(scen["settlements"][2]["id"])  # H joins the population
        rev_h = get_review_for_assignment(scen["assignments"][2]["id"])
        scored_h = validate_success(api.compute_score(rev_h["id"], VM))
        assert scored_h["sales_percentile"] == 67, "population N=3: round_half_up(100*2/3)"
        assert scored_h["official_score"] == 87
        assert scored_h["status"] == "SCORED"

    def test_lowest_gross_computed_last_scores_zero_and_ineligible(self, api):
        """PRD §3.8: "the percentile is one hundred times the number of population
        members whose final gross is strictly less than this assignment's final
        gross, divided by the population size, rounded half-up to an integer
        between 0 and 100."
        PRD §3.8: "If the `official_score` is below 70, the review moves directly
        to `INELIGIBLE` rather than `SCORED`."

        Design: Difficulty/combinatorial_formula/percentile_population_fixed_at_compute_time
        """
        scen = _setup_percentile_trio()
        finalize_settlement(scen["settlements"][2]["id"])  # H finalizes; N=3 for everyone now
        rev_f = get_review_for_assignment(scen["assignments"][0]["id"])
        scored_f = validate_success(api.compute_score(rev_f["id"], VM))
        assert scored_f["sales_percentile"] == 0, "no peer strictly below 100000"
        assert scored_f["official_score"] == 60, "round_half_up((0 + 3000 + 3000)/100)"
        assert scored_f["status"] == "INELIGIBLE", "auto-threshold 60 < 70"
