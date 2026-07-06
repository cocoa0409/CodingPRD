"""Tare/weight tiered line pricing: the shared refill-line price rule at both
the provisional and final stages, the tier x discount x per-line-rounding
combinatorial formula, and the bulk-tier weight boundary.

All Difficulty-queue instances. The default product is Oats
(unit 40, bulk 30 at >= 1000g); PLUS members receive a 0.10 goods discount.
"""
from test_helpers import fixtures, assert_refill_line


class TestProvisionalVsFinalDivergence:
    """One line priced two ways: PROVISIONAL (declared tare + estimate) vs FINAL
    (measured tare + weighed gross), which cross the bulk-tier boundary."""

    def test_provisional_line_price_uses_declared_tare_and_estimate(self, api):
        """PRD §3.5: "In the provisional stage the net weight is
        `estimated_gross_g` minus `declared_tare_g`; in the final stage it is
        `gross_weight_g` minus the container's `measured_tare_g`."
        PRD §3.5: "The `line_price_cents` is that discounted goods value rounded
        half up to a whole cent, rounded per line."

        Design: Difficulty/dual_variant_calc/line_price_provisional_vs_final_divergence
        """
        # PLUS member, BYO tare 200, estimated_gross 1150 -> net 950 -> unit rate
        # 40 -> goods 380 -> PLUS x0.90 -> 342.
        s = fixtures.setup_cart_line(api, member_tier="PLUS", declared_tare_g=200,
                                     estimated_gross_g=1150)
        line = s["line"]
        assert_refill_line(line)
        assert line["net_weight_g"] == 950
        assert line["pricing_stage"] == "PROVISIONAL"
        assert line["line_price_cents"] == 342

    def test_final_line_price_diverges_after_weighing(self, api):
        """PRD §3.5: "Because the final weighed net weight can cross the bulk-tier
        boundary that the provisional estimate did not (or fall short of one it
        did), the final price can legitimately differ from the provisional
        estimate."
        PRD §3.5: "if the net weight is greater than or equal to the product's
        `bulk_tier_threshold_g`, the discounted `bulk_tier_price_cents_per_100g`
        applies; otherwise the base `unit_price_cents_per_100g` applies."

        Design: Difficulty/dual_variant_calc/line_price_provisional_vs_final_divergence
        """
        # FINAL: gross 1250, measured tare 200 -> net 1050 >= 1000 -> bulk rate 30
        # -> goods 315 -> PLUS x0.90 -> 283.5 -> round half up -> 284.
        s = fixtures.setup_final_line(api, member_tier="PLUS", declared_tare_g=200,
                                      estimated_gross_g=1150,
                                      gross_weight_g=1250, measured_tare_g=200)
        line = s["line"]
        assert line["pricing_stage"] == "FINAL"
        assert line["net_weight_g"] == 1050
        assert line["line_price_cents"] == 284


class TestTierAndDiscountCombination:
    """The >=3-input non-linear formula: net-weight tier branch nested with the
    PLUS discount factor and per-line round-half-up."""

    def test_bulk_tier_and_plus_discount_selects_bulk_net_weight(self, api):
        """PRD §3.5: "On a successful fill, ... its `net_weight_g` is recomputed
        as `gross_weight_g` minus the container's `measured_tare_g`."

        Design: Difficulty/combinatorial_formula/tiered_price_tier_and_discount_nonlinear
        """
        s = fixtures.setup_final_line(api, member_tier="PLUS", declared_tare_g=200,
                                      estimated_gross_g=1150,
                                      gross_weight_g=1250, measured_tare_g=200)
        assert s["line"]["net_weight_g"] == 1050

    def test_bulk_tier_and_plus_discount_price_is_284(self, api):
        """PRD §3.5: "If the owning member's `membership_tier` is `PLUS`, the goods
        value is then multiplied by 0.90 (one minus the 0.10 discount factor); a
        `BASIC` member's goods value is unchanged."
        PRD §3.5: "The `line_price_cents` is that discounted goods value rounded
        half up to a whole cent, rounded per line."

        Design: Difficulty/combinatorial_formula/tiered_price_tier_and_discount_nonlinear
        """
        # net 1050 >= 1000 -> bulk 30 -> 315 -> x0.90 -> 283.5 -> 284.
        s = fixtures.setup_final_line(api, member_tier="PLUS", declared_tare_g=200,
                                      estimated_gross_g=1150,
                                      gross_weight_g=1250, measured_tare_g=200)
        assert s["line"]["line_price_cents"] == 284


class TestBulkTierBoundary:
    """Weight-threshold boundary: net exactly at bulk_tier_threshold_g selects the
    bulk rate (>= boundary); one gram below selects the unit rate."""

    def test_net_weight_exactly_at_threshold_uses_bulk_rate(self, api):
        """PRD §3.5: "if the net weight is greater than or equal to the product's
        `bulk_tier_threshold_g`, the discounted `bulk_tier_price_cents_per_100g`
        applies; otherwise the base `unit_price_cents_per_100g` applies."

        Design: Difficulty/boundary_precision_check/bulk_tier_at_exactly_threshold
        """
        # BASIC, net = 1200 - 200 = 1000 == threshold -> bulk 30 -> 300.
        s = fixtures.setup_final_line(api, member_tier="BASIC", declared_tare_g=200,
                                      estimated_gross_g=1200,
                                      gross_weight_g=1200, measured_tare_g=200)
        assert s["line"]["net_weight_g"] == 1000
        assert s["line"]["line_price_cents"] == 300

    def test_net_weight_just_below_threshold_uses_unit_rate(self, api):
        """PRD §3.5: "if the net weight is greater than or equal to the product's
        `bulk_tier_threshold_g`, the discounted `bulk_tier_price_cents_per_100g`
        applies; otherwise the base `unit_price_cents_per_100g` applies."

        Design: Difficulty/boundary_precision_check/bulk_tier_at_exactly_threshold
        """
        # BASIC, net = 1199 - 200 = 999 < 1000 -> unit 40 -> 399.6 -> round half up 400.
        s = fixtures.setup_final_line(api, member_tier="BASIC", declared_tare_g=200,
                                      estimated_gross_g=1200,
                                      gross_weight_g=1199, measured_tare_g=200)
        assert s["line"]["net_weight_g"] == 999
        assert s["line"]["line_price_cents"] == 400
