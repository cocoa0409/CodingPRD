"""Difficulty queue: combinatorial buy-in price formula (discount x proration x floor)."""
import pytest

from test_helpers import (
    create_buy_in_offer,
    create_physician,
    create_policy,
)


class TestBuyInPriceTenureDiscountProrationFloor:
    def test_mid_tenure_discount_and_proration_and_schedule(self, api):
        """PRD §3.2: "The discounted base is the tier base multiplied by one minus the
        discount percentage; the prorated amount is the discounted base multiplied by
        `proration_twelfths` and divided by 12, rounded half-up to whole cents — the
        only rounding step in this calculation. `final_amount_cents` is the prorated
        amount, but never below `min_buy_in_cents`. The `installment_schedule_cents`
        splits the final amount into `installment_count` equal parts by flooring, with
        the remainder cents placed on the first installment — so the first entry is
        the floor plus the residue and every later entry is the floor."
        P1 hired 2020-07-01 offered at the 2026-08-01 default clock: 6 full
        365.25-day years -> discount 0.12; August -> proration_twelfths 11;
        round(25000000 * 0.88 * 11/12) = 20166667.

        Design: Difficulty/combinatorial_formula/buy_in_price_tenure_discount_proration_floor
        """
        create_policy(total_shares_authorized=1000000)
        p1 = create_physician(full_name="Dr P1", hire_date="2020-07-01T00:00:00Z")
        offer = create_buy_in_offer(
            p1["id"], target_tier="SHAREHOLDER", share_grant=500, installment_count=3
        )
        assert offer["discount_pct_applied"] == pytest.approx(0.12)
        assert offer["proration_twelfths"] == 11
        assert offer["final_amount_cents"] == 20166667, (
            f"expected round(25000000*0.88*11/12) = 20166667, got {offer['final_amount_cents']}"
        )
        assert offer["installment_schedule_cents"] == [6722223, 6722222, 6722222], (
            "floor split with the remainder cent on the FIRST installment"
        )
        assert offer["tenure_years_at_offer"] == 6

    def test_tenure_discount_capped_at_max(self, api):
        """PRD §3.2: "The discount percentage, `discount_pct_applied`, is the smaller
        of `tenure_years_at_offer` multiplied by `tenure_discount_pct_per_year` and
        `max_tenure_discount_pct` — with the defaults, 2 percent per year of tenure,
        capped at 20 percent."
        P2 hired 2000-01-01 offered at the 2026-08-01 default clock: 26 full years ->
        26 * 0.02 = 0.52 capped at 0.20; round(25000000 * 0.80 * 11/12) = 18333333.

        Design: Difficulty/combinatorial_formula/buy_in_price_tenure_discount_proration_floor
        """
        create_policy(total_shares_authorized=1000000)
        p2 = create_physician(full_name="Dr P2", hire_date="2000-01-01T00:00:00Z")
        offer = create_buy_in_offer(
            p2["id"], target_tier="SHAREHOLDER", share_grant=500, installment_count=3
        )
        assert offer["discount_pct_applied"] == pytest.approx(0.20), (
            "26 years * 0.02 must be capped at max_tenure_discount_pct 0.20"
        )
        assert offer["proration_twelfths"] == 11
        assert offer["final_amount_cents"] == 18333333, (
            f"expected round(25000000*0.80*11/12) = 18333333, got {offer['final_amount_cents']}"
        )
