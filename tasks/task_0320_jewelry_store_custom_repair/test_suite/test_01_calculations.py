"""Calculation-depth tests: dual-variant totals, combinatorial valuation, boundary clamps.

Translates queue-A difficulty instances under rule_ids dual_variant_calc,
combinatorial_formula, and boundary_precision_check. Literal expected values are
copied verbatim from the design index (already pre-computed integer cents).
"""
import pytest
from test_helpers import (
    validate_success,
    create_ready_custom_order,
    create_quoted_custom_order,
    create_active_layaway_plan,
    pay_layaway_installment,
    create_trade_in_offer,
    create_assessed_repair_ticket,
    TEST_USERS,
    api_client,
)

SM = TEST_USERS["store_manager_headers"]

# Three fractional-cent line items shared by the custom-order dual-variant instances.
DUAL_VARIANT_LINE_ITEMS = [
    {"qty": 1, "unit_price_cents": 99990, "markup_pct": 0.175},
    {"qty": 1, "unit_price_cents": 49995, "markup_pct": 0.175},
    {"qty": 1, "unit_price_cents": 24997, "markup_pct": 0.175},
]


class TestCustomOrderDualVariant:
    def test_provisional_and_final_totals_differ_on_same_order(self, api):
        """PRD §3.3: "the `provisional_total_cents` is the `estimated_materials_cents`
        marked up by 20 percent — that is, the estimated materials multiplied by 1.20
        and rounded half up — then the flat `design_fee_cents` added on top."
        PRD §3.3: "The final total is built by taking, for each line, the product of its
        `qty`, its `unit_price_cents`, and one plus its `markup_pct`, rounding that line
        to whole cents half up, and only then summing the rounded line totals; the flat
        `design_fee_cents` is added to that sum."

        Design: Difficulty/dual_variant_calc/custom_order_provisional_vs_final_total
        """
        order, _ = create_ready_custom_order(
            DUAL_VARIANT_LINE_ITEMS,
            deposit_cents=144000,
            estimated_materials_cents=300000,
            design_fee_cents=120000,
        )
        assert order["provisional_total_cents"] == 480000
        assert order["final_total_cents"] == 325603
        assert order["balance_due_cents"] == 181603
        assert order["status"] == "READY"

    def test_provisional_total_computed_at_quote_independent_of_final(self, api):
        """PRD §3.3: "the `provisional_total_cents` is the `estimated_materials_cents`
        marked up by 20 percent — that is, the estimated materials multiplied by 1.20
        and rounded half up — then the flat `design_fee_cents` added on top."
        PRD §3.3: "From that, the `deposit_required_cents` is 30 percent of the provisional
        total, rounded half up."

        Design: Difficulty/dual_variant_calc/custom_order_provisional_vs_final_total
        """
        # At QUOTED (before line items / production), only the provisional variant exists.
        order, _ = create_quoted_custom_order(
            estimated_materials_cents=300000, design_fee_cents=120000
        )
        assert order["provisional_total_cents"] == 480000
        assert order["deposit_required_cents"] == 144000
        assert order["status"] == "QUOTED"

    def test_final_total_rounds_per_line_before_summation(self, api):
        """PRD §3.3: "Rounding is applied per line before the lines are added — not by
        summing first and rounding once — and the two approaches can legitimately differ
        by a cent."
        PRD §3.3: "Completing production is where the `final_total_cents` is computed from
        the persisted line items."

        Design: Difficulty/combinatorial_formula/custom_order_final_total_round_per_line_then_sum
        """
        order, _ = create_ready_custom_order(
            DUAL_VARIANT_LINE_ITEMS,
            deposit_cents=144000,
            estimated_materials_cents=300000,
            design_fee_cents=120000,
        )
        assert order["final_total_cents"] == 325603

    def test_balance_due_recomputed_from_final_total_after_production(self, api):
        """PRD §3.3: "Completing production also recomputes the `balance_due_cents`: once
        production is complete the balance is the `final_total_cents` minus
        `deposit_paid_cents`".

        Design: Difficulty/combinatorial_formula/custom_order_final_total_round_per_line_then_sum
        """
        order, _ = create_ready_custom_order(
            DUAL_VARIANT_LINE_ITEMS,
            deposit_cents=144000,
            estimated_materials_cents=300000,
            design_fee_cents=120000,
        )
        # final_total 325603 - deposit_paid 144000 = 181603.
        assert order["final_total_cents"] == 325603
        assert order["balance_due_cents"] == 181603


class TestLayawayDualVariant:
    def test_projected_payoff_vs_settlement_refund(self, api):
        """PRD §3.5: "The `projected_payoff_cents` — what the customer pays if they
        complete the plan on schedule with no fees — equals the snapshot
        `item_price_cents` exactly."
        PRD §3.5: "The `settlement_refund_cents` is whatever the customer has paid to date
        minus that restocking fee, but never below 0."
        PRD §3.5: "The `restocking_fee_cents` is the smaller of 50000 cents and 15 percent
        of the snapshot `item_price_cents` rounded half up — that is, the restocking fee is
        capped at 50000 cents."

        Design: Difficulty/dual_variant_calc/layaway_projected_payoff_vs_settlement_refund
        """
        plan, customer_id, item = create_active_layaway_plan(
            item_price_cents=600000, installment_count=6
        )
        assert plan["projected_payoff_cents"] == 600000
        # Two 80000 installments on top of the 120000 down payment -> paid_to_date 280000.
        plan = pay_layaway_installment(plan, 80000)
        plan = pay_layaway_installment(plan, 80000)
        cancelled = validate_success(
            api.cancel_layaway_plan(plan["id"], {"expected_version": plan["version"]}, SM), 200
        )
        assert cancelled["restocking_fee_cents"] == 50000
        assert cancelled["settlement_refund_cents"] == 230000
        assert cancelled["status"] == "CANCELLED"
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 230000

    def test_settlement_refund_posts_full_refund_to_store_credit(self, api):
        """PRD §3.5: "If the settlement refund is greater than 0, the system posts a
        `CreditLedgerEntry` with direction `CREDIT`, `amount_cents` equal to the settlement
        refund, and reason `LAYAWAY_REFUND`, then recomputes the customer's
        `store_credit_balance_cents`."

        Design: Difficulty/dual_variant_calc/layaway_projected_payoff_vs_settlement_refund
        """
        plan, customer_id, item = create_active_layaway_plan(
            item_price_cents=600000, installment_count=6
        )
        plan = pay_layaway_installment(plan, 80000)
        plan = pay_layaway_installment(plan, 80000)
        cancelled = validate_success(
            api.cancel_layaway_plan(plan["id"], {"expected_version": plan["version"]}, SM), 200
        )
        assert cancelled["settlement_refund_cents"] == 230000
        customer = validate_success(api.get_customer(customer_id, SM), 200)
        assert customer["store_credit_balance_cents"] == 230000


class TestTradeInCombinatorial:
    def test_tiered_purity_and_condition_credit(self, api):
        """PRD §3.6: "The `metal_value_cents` is the `metal_weight_grams` multiplied by the
        `metal_spot_price_cents_per_gram` multiplied by the purity factor for the karat,
        rounded half up; the purity factor is 0.585 for `K14`, 0.750 for `K18`, and 1.000
        for `K24`."
        PRD §3.6: "A raw credit is then formed by adding the `gemstone_value_cents` to the
        `metal_value_cents`, multiplying by the condition factor, and rounding half up; the
        condition factor is 0.90 for `EXCELLENT`, 0.75 for `GOOD`, and 0.55 for `FAIR`."

        Design: Difficulty/combinatorial_formula/trade_in_credit_tiered_nested_min_max
        """
        offer, _ = create_trade_in_offer(
            metal_karat="K18",
            metal_weight_grams=12.0,
            metal_spot_price_cents_per_gram=6000,
            gemstone_value_cents=150000,
            condition="GOOD",
        )
        assert offer["metal_value_cents"] == 54000
        assert offer["buyback_credit_cents"] == 153000
        assert offer["status"] == "OFFERED"

    def test_unclamped_raw_credit_is_observable_buyback(self, api):
        """PRD §3.6: "The `buyback_credit_cents` is that raw credit clamped to the range
        from a 2500-cent floor to a 5000000-cent ceiling — that is, never less than 2500
        cents and never more than 5000000 cents."
        PRD §3.6: "The valuation is computed at creation from these snapshot inputs and is
        never recomputed afterward."

        Design: Difficulty/combinatorial_formula/trade_in_credit_tiered_nested_min_max
        """
        # raw credit 153000 lies strictly inside [2500, 5000000], so the clamp is inert.
        offer, _ = create_trade_in_offer(
            metal_karat="K18",
            metal_weight_grams=12.0,
            metal_spot_price_cents_per_gram=6000,
            gemstone_value_cents=150000,
            condition="GOOD",
        )
        assert offer["buyback_credit_cents"] == 153000


class TestBoundaryPrecision:
    def test_rush_subtotal_50000_takes_mid_tier(self, api):
        """PRD §3.4: "20 percent when the subtotal is from 10000 cents up to and including
        50000 cents, and 30 percent when the subtotal exceeds 50000 cents (so a subtotal of
        exactly 50000 cents takes the 20-percent tier, and 50001 cents takes the 30-percent
        tier)."

        Design: Difficulty/boundary_precision_check/repair_rush_tier_boundary_50000_inclusive_mid
        """
        ticket, _ = create_assessed_repair_ticket(
            20000, 30000, repair_kind="STONE_RESET", rush=True
        )
        assert ticket["rush_surcharge_cents"] == 10000
        assert ticket["total_cents"] == 60000

    def test_rush_subtotal_exactly_50000_does_not_take_high_tier(self, api):
        """PRD §3.4: "20 percent when the subtotal is from 10000 cents up to and including
        50000 cents, and 30 percent when the subtotal exceeds 50000 cents (so a subtotal of
        exactly 50000 cents takes the 20-percent tier, and 50001 cents takes the 30-percent
        tier)."

        Design: Difficulty/boundary_precision_check/repair_rush_tier_boundary_50000_inclusive_mid
        """
        # Same boundary subtotal 50000 via a different parts/labor split -> still MID (0.20).
        ticket, _ = create_assessed_repair_ticket(
            50000, 0, repair_kind="STONE_RESET", rush=True
        )
        # 0.30 would give 15000/65000; the inclusive MID bound yields 10000/60000.
        assert ticket["rush_surcharge_cents"] == 10000
        assert ticket["total_cents"] == 60000

    def test_trade_in_raw_credit_below_floor_clamped_to_2500(self, api):
        """PRD §3.6: "The `buyback_credit_cents` is that raw credit clamped to the range
        from a 2500-cent floor to a 5000000-cent ceiling — that is, never less than 2500
        cents and never more than 5000000 cents."

        Design: Difficulty/boundary_precision_check/trade_in_min_buyback_clamp_floor
        """
        offer, _ = create_trade_in_offer(
            metal_karat="K14",
            metal_weight_grams=0.2,
            metal_spot_price_cents_per_gram=3000,
            gemstone_value_cents=0,
            condition="FAIR",
        )
        assert offer["metal_value_cents"] == 351
        assert offer["buyback_credit_cents"] == 2500

    def test_floored_buyback_offer_created_in_offered_state(self, api):
        """PRD §3.6: "The `buyback_credit_cents` is that raw credit clamped to the range
        from a 2500-cent floor to a 5000000-cent ceiling — that is, never less than 2500
        cents and never more than 5000000 cents."
        PRD §3.6: "A new offer is `OFFERED`."

        Design: Difficulty/boundary_precision_check/trade_in_min_buyback_clamp_floor
        """
        # metal_value 351, raw credit 351*0.55 = 193 < 2500 floor -> clamped to 2500.
        offer, _ = create_trade_in_offer(
            metal_karat="K14",
            metal_weight_grams=0.2,
            metal_spot_price_cents_per_gram=3000,
            gemstone_value_cents=0,
            condition="FAIR",
        )
        assert offer["buyback_credit_cents"] == 2500
        assert offer["status"] == "OFFERED"
