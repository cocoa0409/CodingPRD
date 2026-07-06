"""Pier-and-anchor subtotal and financing pricing (PRD §3.3, §3.6).

Depth tiers, soil/access multipliers, pinned rounding order, the volume-discount /
financed-principal / financing-fee chain, and estimate-vs-final divergence.
"""
from test_helpers import (
    validate_success,
    setup_sent_quote,
    setup_completed_install,
)


class TestPierPricingCombinatorial:
    def test_pier_subtotal_nonlinear_multi_input(self, api):
        """PRD §3.3: "That base is multiplied by the soil multiplier keyed on the source
        inspection's `soil_class` — 1.00 for `STABLE`, 1.15 for `EXPANSIVE`, 1.30 for
        `UNSTABLE` — and by the access multiplier keyed on the scope's `access_difficulty`
        — 1.00 for `EASY`, 1.10 for `MODERATE`, 1.25 for `HARD`."
        PRD §3.3: "The rounding order is fixed: round the per-pier amount before multiplying
        by the count."

        Design: Difficulty/combinatorial_formula/pier_pricing_nonlinear_multi_input
        """
        ctx = setup_sent_quote(
            soil_class="UNSTABLE", financing_plan="CASH", pier_count=12,
            anchor_count=0, avg_pier_depth_ft=26, access_difficulty="HARD",
            supplemental_engineering=True,
        )
        assert ctx["quote"]["subtotal_cents"] == 4095000, ctx["quote"]

    def test_pier_total_cash_no_fee(self, api):
        """PRD §3.3: "If the gross subtotal is at least 2,000,000 cents
        (`VOLUME_DISCOUNT_THRESHOLD_CENTS`), a volume discount equal to the gross subtotal
        times 0.05 (`VOLUME_DISCOUNT_RATE`), rounded half-up to a whole cent, is applied;
        otherwise the discount is zero."
        PRD §3.3: "Finally, `total_cents` is the financed principal plus the financing fee."

        Design: Difficulty/combinatorial_formula/pier_pricing_nonlinear_multi_input
        """
        ctx = setup_sent_quote(
            soil_class="UNSTABLE", financing_plan="CASH", pier_count=12,
            anchor_count=0, avg_pier_depth_ft=26, access_difficulty="HARD",
            supplemental_engineering=True,
        )
        # CASH fee rate 0.00 -> total == financed principal (4095000 - 204750 discount).
        assert ctx["quote"]["total_cents"] == 3890250, ctx["quote"]


class TestFinancingPinnedOrder:
    def test_financing_fee_on_financed_principal(self, api):
        """PRD §3.3: "The financing fee is the financed principal times the plan rate for
        the quote's `financing_plan` — 0.00 for `CASH`, 0.05 for `PLAN_12`, 0.12 for
        `PLAN_60` — rounded half-up to a whole cent; the fee is computed on the financed
        principal, not on the gross subtotal."

        Design: Difficulty/combinatorial_formula/financing_total_pinned_evaluation_order
        """
        ctx = setup_sent_quote(
            soil_class="UNSTABLE", financing_plan="PLAN_60", pier_count=12,
            anchor_count=0, avg_pier_depth_ft=26, access_difficulty="HARD",
            supplemental_engineering=True,
        )
        # fee = round(financed_principal 3890250 * 0.12) = 466830.
        assert ctx["quote"]["financing_fee_cents"] == 466830, ctx["quote"]

    def test_financing_total_after_discount_and_fee(self, api):
        """PRD §3.3: "The financed principal is the gross subtotal minus that discount."
        PRD §3.3: "Finally, `total_cents` is the financed principal plus the financing fee."

        Design: Difficulty/combinatorial_formula/financing_total_pinned_evaluation_order
        """
        ctx = setup_sent_quote(
            soil_class="UNSTABLE", financing_plan="PLAN_60", pier_count=12,
            anchor_count=0, avg_pier_depth_ft=26, access_difficulty="HARD",
            supplemental_engineering=True,
        )
        # total = financed_principal 3890250 + fee 466830.
        assert ctx["quote"]["total_cents"] == 4357080, ctx["quote"]


class TestDepthTierBoundary:
    def test_depth_15ft_inclusive_to_tier2(self, api):
        """PRD §3.3: "a depth of at least 15 feet but below 25 feet takes the tier-2 base of
        165,000 cents (`PIER_TIER2_CENTS`)"

        Design: Difficulty/boundary_precision_check/pier_depth_tier_boundary_15ft_inclusive
        """
        ctx = setup_sent_quote(
            soil_class="STABLE", financing_plan="CASH", pier_count=1,
            anchor_count=0, avg_pier_depth_ft=15.0, access_difficulty="EASY",
        )
        # 1 pier, STABLE(1.0), EASY(1.0), 0 anchors -> subtotal == tier-2 base 165000.
        assert ctx["quote"]["subtotal_cents"] == 165000, ctx["quote"]

    def test_depth_below_15ft_uses_tier1(self, api):
        """PRD §3.3: "a depth below 15 feet takes the tier-1 base of 120,000 cents
        (`PIER_TIER1_CENTS`)"

        Design: Difficulty/boundary_precision_check/pier_depth_tier_boundary_15ft_inclusive
        """
        ctx = setup_sent_quote(
            soil_class="STABLE", financing_plan="CASH", pier_count=1,
            anchor_count=0, avg_pier_depth_ft=14.0, access_difficulty="EASY",
        )
        # Just below the 15 ft boundary -> tier-1 base 120000 (not 165000).
        assert ctx["quote"]["subtotal_cents"] == 120000, ctx["quote"]


class TestDualVariantPricing:
    def test_quote_estimate_total(self, api):
        """PRD §3.3: "The per-pier amount is then multiplied by the pier count (the
        engineered `pier_count` in the estimate variant), giving the pier portion of the
        subtotal."

        Design: Difficulty/dual_variant_calc/quote_estimate_vs_job_final_pricing
        """
        ctx = setup_completed_install(
            soil_class="EXPANSIVE", financing_plan="PLAN_12", pier_count=8,
            anchor_count=2, avg_pier_depth_ft=18, access_difficulty="MODERATE",
            piers_installed=9,
        )
        # Estimate variant priced from engineered pier_count=8.
        assert ctx["quote"]["total_cents"] == 1847790, ctx["quote"]

    def test_job_final_total_diverges_from_estimate(self, api):
        """PRD §3.6: "The final variant of pier pricing is identical to the estimate variant
        except that the pier count used is the actual `piers_installed` rather than the
        engineered `pier_count`; it writes `final_subtotal_cents`, and the two figures
        diverge exactly when `piers_installed` differs from `pier_count`."

        Design: Difficulty/dual_variant_calc/quote_estimate_vs_job_final_pricing
        """
        ctx = setup_completed_install(
            soil_class="EXPANSIVE", financing_plan="PLAN_12", pier_count=8,
            anchor_count=2, avg_pier_depth_ft=18, access_difficulty="MODERATE",
            piers_installed=9,
        )
        job = ctx["job"]
        # Final variant priced from actual piers_installed=9.
        assert job["final_total_cents"] == 2066951, job
        assert job["final_total_cents"] != ctx["quote"]["total_cents"]
