"""Multi-input formulas whose composition order and bracket decomposition are pinned."""

from test_helpers import (
    AccrualStatus,
    AllocationBasis,
    FeeType,
    FeeVariant,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    find_accrual,
    no_rows,
)


def _three_line_rounding_inn(scenario):
    agreement = scenario.register(
        hotel_name="Three Line Rounding Inn",
        owner_entity_name="Line Item Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
        budgeted_capital_ffe_cents=0,
        budgeted_capital_brand_cents=0,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])
    package = scenario.expert_package(agreement["id"])
    scenario.submit_package(package["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestBaseFeeRoundedPerRevenueLine:
    def test_three_revenue_lines_round_individually_before_they_are_summed(self, scenario):
        """PRD §3.4: "each of the three revenue lines is multiplied by the agreement's
        `base_fee_pct` and rounded half up to whole cents" and "Summing the revenue first
        and rounding once is not the contractual order and can differ by a cent, so it is
        not permitted."

        Design: Difficulty/combinatorial_formula/base_fee_rounded_per_revenue_line_then_summed
        """
        state = _three_line_rounding_inn(scenario)

        package = scenario.read_package(state["package_id"])

        assert package["gross_revenue_cents"] == 55000025
        # 1300000 + 390000 + 97500, not the 1787501 of a single rounding.
        assert package["base_fee_cents"] == 1787500
        assert package["base_fee_cents"] != 1787501
        assert package["allocated_centralized_cents"] == 0

    def test_agop_and_provisional_incentive_carry_the_per_line_fee(self, scenario):
        """PRD §3.4: "`agop_cents` — the adjusted gross operating profit — is the package's
        `gross_revenue_cents` less its `operating_expenses_cents`, less its
        `base_fee_cents`, less its `allocated_centralized_cents`, with no intermediate
        rounding inside that subtraction."

        Design: Difficulty/combinatorial_formula/base_fee_rounded_per_revenue_line_then_summed
        """
        state = _three_line_rounding_inn(scenario)

        package = scenario.read_package(state["package_id"])

        assert package["agop_cents"] == 23212525
        assert package["incentive_fee_provisional_cents"] == 2221253

    def test_submit_raises_a_base_accrual_holding_the_summed_line_fee(self, scenario):
        """PRD §3.4: "Each submit raises a fresh set of fee accruals in `ACCRUED`: a `BASE`
        accrual of `variant` `PROVISIONAL` carrying `base_fee_cents`"

        Design: Difficulty/combinatorial_formula/base_fee_rounded_per_revenue_line_then_summed
        """
        state = _three_line_rounding_inn(scenario)

        accruals = scenario.accruals(state["package_id"])
        base = find_accrual(accruals, FeeType.BASE, FeeVariant.PROVISIONAL)

        assert base["amount_cents"] == 1787500
        assert base["status"] == AccrualStatus.ACCRUED


def _bracket_split_hotel(scenario):
    agreement = scenario.register(
        hotel_name="Bracket Split Hotel",
        owner_entity_name="Two Tier Owner LP",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        incentive_tier2_pct=0.15,
        incentive_tier2_threshold_cents=5000000,
        owner_priority_cents=12000000,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
        budgeted_capital_ffe_cents=0,
        budgeted_capital_brand_cents=0,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])

    profit_month = scenario.expert_package(
        agreement["id"], fiscal_year=2026, period_month=9, closing_cash_available_cents=0
    )
    scenario.submit_package(profit_month["id"])
    scenario.review_package(profit_month["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

    loss_month = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=10,
        rooms_revenue_cents=4000000,
        fnb_revenue_cents=1000000,
        other_revenue_cents=0,
        operating_expenses_cents=9000000,
        closing_cash_available_cents=0,
    )
    scenario.submit_package(loss_month["id"])
    scenario.review_package(loss_month["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

    return {
        "agreement_id": agreement["id"],
        "profit_month_id": profit_month["id"],
        "loss_month_id": loss_month["id"],
    }


class TestAnnualIncentiveBracketSplit:
    def test_each_bracket_is_rounded_on_its_own_rather_than_blended(self, scenario):
        """PRD §3.8: "Each tier is rounded on its own and the two rounded products are then
        added; the excess is never multiplied by a blended rate."

        Design: Difficulty/combinatorial_formula/annual_incentive_two_tier_bracket_split_over_netted_agop
        """
        state = _bracket_split_hotel(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        # Excess 7050025: 5000000 at 0.10 is 500000, 2050025 at 0.15 is 307504.
        assert summary["final_incentive_fee_cents"] == 807504
        assert summary["final_incentive_fee_cents"] != 705003

    def test_loss_month_nets_into_the_annual_figure_but_not_into_the_provisionals(self, scenario):
        """PRD §3.8: "`annual_agop_cents` is the sum of `agop_cents` over them — a sum in
        which a negative month genuinely reduces the annual total." PRD §3.4: "because each
        month is floored independently, loss months never offset profit months in the
        provisional accrual."

        Design: Difficulty/combinatorial_formula/annual_incentive_two_tier_bracket_split_over_netted_agop
        """
        state = _bracket_split_hotel(scenario)

        profit = scenario.read_package(state["profit_month_id"])
        loss = scenario.read_package(state["loss_month_id"])
        assert profit["agop_cents"] == 23212525
        assert profit["incentive_fee_provisional_cents"] == 2221253
        assert loss["agop_cents"] == -4162500
        assert loss["incentive_fee_provisional_cents"] == 0

        summary = scenario.true_up(state["agreement_id"], 2026)
        assert summary["accepted_period_count"] == 2
        assert summary["annual_agop_cents"] == 19050025
        assert summary["provisional_incentive_total_cents"] == 2221253
        assert summary["true_up_delta_cents"] == -1413749

    def test_settlement_accrual_lands_on_the_highest_accepted_period_month(self, scenario):
        """PRD §3.8: "attached to the accepted period with the highest `period_month`"

        Design: Difficulty/combinatorial_formula/annual_incentive_two_tier_bracket_split_over_netted_agop
        """
        state = _bracket_split_hotel(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["attached_report_package_id"] == state["loss_month_id"]
        final = find_accrual(
            scenario.accruals(state["loss_month_id"]), FeeType.INCENTIVE, FeeVariant.FINAL
        )
        assert final["id"] == summary["true_up_accrual_id"]
        assert final["amount_cents"] == -1413749
        assert final["report_package_id"] == state["loss_month_id"]


def _order_of_operations_suites(scenario):
    agreement = scenario.register(
        hotel_name="Order Of Operations Suites",
        owner_entity_name="Pinned Order Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
        budgeted_capital_ffe_cents=0,
        budgeted_capital_brand_cents=0,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])
    package = scenario.expert_package(agreement["id"])
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "charge_id": charge["id"],
    }


class TestAgopPinnedEvaluationOrder:
    def test_centralized_allocation_settles_before_the_fee_is_struck(self, scenario):
        """PRD §3.4: "First the centralized allocation is settled as described above,
        producing `allocated_centralized_cents`."

        Design: Difficulty/combinatorial_formula/agop_pinned_evaluation_order_centralized_then_fee_then_priority
        """
        state = _order_of_operations_suites(scenario)

        charges = scenario.charges(state["package_id"])
        charge = next(row for row in charges if row["id"] == state["charge_id"])
        # The period ceiling is floor(55000025 * 0.015) == 825000, so 500000 fits whole.
        assert charge["requested_amount_cents"] == 500000
        assert charge["allocated_amount_cents"] == 500000

        package = scenario.read_package(state["package_id"])
        assert package["allocated_centralized_cents"] == 500000
        assert package["base_fee_cents"] == 1787500

    def test_reserve_contribution_is_never_deducted_from_agop(self, scenario):
        """PRD §3.4: "`agop_cents` — the adjusted gross operating profit — is the package's
        `gross_revenue_cents` less its `operating_expenses_cents`, less its
        `base_fee_cents`, less its `allocated_centralized_cents`, with no intermediate
        rounding inside that subtraction."

        Design: Difficulty/combinatorial_formula/agop_pinned_evaluation_order_centralized_then_fee_then_priority
        """
        state = _order_of_operations_suites(scenario)

        package = scenario.read_package(state["package_id"])

        assert package["agop_cents"] == 22712525
        # Deducting the 2200001 reserve contribution would have produced 20512524.
        assert package["agop_cents"] != 20512524
        assert package["incentive_fee_provisional_cents"] == 2171253

    def test_reporting_leaves_the_reserve_balance_at_zero(self, scenario):
        """PRD §2.9: "the agreement's `ffe_reserve_balance_cents` equals the signed sum of
        `amount_cents` across every reserve ledger entry of that agreement"

        Design: Difficulty/combinatorial_formula/agop_pinned_evaluation_order_centralized_then_fee_then_priority
        """
        state = _order_of_operations_suites(scenario)

        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 0
        no_rows(scenario.ledger(state["agreement_id"]))
