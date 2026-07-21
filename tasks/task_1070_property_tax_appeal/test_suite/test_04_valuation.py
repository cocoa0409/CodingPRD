"""Opinion-of-value: dual-variant median and pinned per-comparable nested rounding (depth coverage)."""
from test_helpers import validate_success, make_analyst_headers
from test_helpers import fixtures as fx


class TestDualVariantValuation:
    """Same three comps, two valuation methods, two different requested values.
    Design: Difficulty/dual_variant_calc/di_valuation_sales_comparison_vs_assessment_equity
    """

    def test_sales_comparison_uses_median_of_adjusted_sale_values(self, api):
        """PRD §3.3: "Under the sales-comparison method the list is each included comparable's
        `adjusted_sale_value_cents`." Median of the three adjusted sale values
        (30000000, 30400000, 29400000) is 30000000.

        Design: Difficulty/dual_variant_calc/di_valuation_sales_comparison_vs_assessment_equity
        """
        ctx = fx.setup_filed_appeal(api, valuation_method="SALES_COMPARISON",
                                    comps=fx.DUAL_VARIANT_COMPS)
        assert ctx["appeal"]["requested_value_cents"] == 30000000

    def test_assessment_equity_uses_median_of_equity_implied_values(self, api):
        """PRD §3.3: "Under the assessment-equity method the list is instead, for each included
        comparable, that comparable's `comp_assessed_value_cents` divided by the jurisdiction's
        `equalization_ratio` and rounded half up to whole cents — the same comparable set measured
        differently, so the two methods generally yield different opinions."
        Median of (31000000, 28000000, 29000000) is 29000000, distinct from the sales-comparison 30000000.

        Design: Difficulty/dual_variant_calc/di_valuation_sales_comparison_vs_assessment_equity
        """
        ctx = fx.setup_filed_appeal(api, valuation_method="ASSESSMENT_EQUITY",
                                    comps=fx.DUAL_VARIANT_COMPS)
        assert ctx["appeal"]["requested_value_cents"] == 29000000
        assert ctx["appeal"]["requested_value_cents"] != 30000000


class TestPerCompRoundingBeforeMedian:
    """Per-comp round-then-median: adjusted values 101 & 102 -> median 102 (not 101).
    Design: Difficulty/combinatorial_formula/ci_valuation_percomp_round_before_median
    """

    def _setup_two_comp_appeal(self, api):
        ctx = fx.setup_base(api, assessment_overrides={"original_assessed_value_cents": 500})
        appeal = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                               "SALES_COMPARISON")
        ctx["appeal_id"] = appeal["id"]
        e1 = fx.add_evidence(api, ctx["analyst_id"], appeal["id"], comp_address="c1",
                             sale_price_cents=100, comp_assessed_value_cents=90, adjustment_pct=0.005)
        e2 = fx.add_evidence(api, ctx["analyst_id"], appeal["id"], comp_address="c2",
                             sale_price_cents=100, comp_assessed_value_cents=90, adjustment_pct=0.015)
        ctx["e1"], ctx["e2"] = e1, e2
        return ctx

    def test_each_comp_is_rounded_individually_first(self, api):
        """PRD §3.3: "the system computes its `adjusted_sale_value_cents` as the `sale_price_cents`
        multiplied by the quantity one plus the `adjustment_pct`, rounded half up to whole cents.
        This per-comparable rounding is pinned to happen before any aggregation across comparables."
        100*1.005 -> 100.5 -> 101; 100*1.015 -> 101.5 -> 102.

        Design: Difficulty/combinatorial_formula/ci_valuation_percomp_round_before_median
        """
        ctx = self._setup_two_comp_appeal(api)
        assert ctx["e1"]["adjusted_sale_value_cents"] == 101
        assert ctx["e2"]["adjusted_sale_value_cents"] == 102

    def test_even_count_median_rounds_half_up(self, api):
        """PRD §3.3: "if the count is even the median is the mean of the two middle figures, rounded
        half up to whole cents ... In both methods the per-comparable figure is rounded before the
        median is taken, and this nested rounding order is binding."
        median(101, 102) = round_half_up(101.5) = 102.

        Design: Difficulty/combinatorial_formula/ci_valuation_percomp_round_before_median
        """
        ctx = self._setup_two_comp_appeal(api)
        appeal = fx.do_file_appeal(api, ctx["analyst_id"], ctx["appeal_id"])
        assert appeal["requested_value_cents"] == 102
