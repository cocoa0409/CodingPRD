"""Two calculations that exist in two variants each, where the variants diverge."""

from test_helpers import (
    AccrualStatus,
    AgreementStatus,
    AllocationBasis,
    BenchmarkSource,
    BudgetSourceStatus,
    FeeType,
    FeeVariant,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    TestStatus,
    assert_gop_achievement,
    assert_rpi,
    find_accrual,
)


def _harborline(scenario):
    """One accepted September period under the two-tier expert configuration."""
    agreement = scenario.register_expert(
        hotel_name="Harborline Grand", owner_entity_name="Pier 9 Hotel Owner LLC"
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
        budgeted_capital_ffe_cents=20000000,
        budgeted_capital_brand_cents=10000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])
    package = scenario.expert_package(agreement["id"])
    scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestIncentiveProvisionalVersusFinal:
    def test_monthly_provisional_charges_a_rounded_priority_twelfth(self, scenario):
        """PRD §3.4: "Fourth, the monthly slice of the owner priority is the agreement's
        `owner_priority_cents` divided by twelve and rounded half up to whole cents.
        Fifth and last, `incentive_fee_provisional_cents` is the package's `agop_cents`
        less that rounded monthly priority slice, multiplied by the agreement's
        `incentive_fee_pct`, rounded half up to whole cents, and floored at zero"

        Design: Difficulty/dual_variant_calc/incentive_provisional_monthly_versus_final_annual_true_up
        """
        state = _harborline(scenario)

        package = scenario.read_package(state["package_id"])

        assert package["agop_cents"] == 22712525
        # 22712525 - 1000000 == 21712525, at 0.10 and rounded half up.
        assert package["incentive_fee_provisional_cents"] == 2171253

    def test_annual_true_up_splits_the_excess_across_two_tiers(self, scenario):
        """PRD §3.8: "The excess is `annual_agop_cents` less the agreement's
        `owner_priority_cents`." and "Where it is positive, the first tier's base is the
        smaller of the excess and the agreement's `incentive_tier2_threshold_cents`, and
        the second tier's base is the excess less that threshold, floored at zero." and
        "Each tier is rounded on its own and the two rounded products are then added; the
        excess is never multiplied by a blended rate."

        Design: Difficulty/dual_variant_calc/incentive_provisional_monthly_versus_final_annual_true_up
        """
        state = _harborline(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["accepted_period_count"] == 1
        assert summary["annual_agop_cents"] == 22712525
        assert summary["provisional_incentive_total_cents"] == 2171253
        # Excess 10712525: 5000000 at 0.10 is 500000, 5712525 at 0.15 is 856879.
        assert summary["final_incentive_fee_cents"] == 1356879
        assert summary["true_up_delta_cents"] == -814374

    def test_final_accrual_is_posted_and_the_provisional_row_is_left_alone(self, scenario):
        """PRD §3.8: "The delta is posted as a new fee accrual with `fee_type` `INCENTIVE`,
        `variant` `FINAL` and `status` `ACCRUED`, attached to the accepted period with the
        highest `period_month`"

        Design: Difficulty/dual_variant_calc/incentive_provisional_monthly_versus_final_annual_true_up
        """
        state = _harborline(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        accruals = scenario.accruals(state["package_id"])
        final = find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.FINAL)
        assert final["id"] == summary["true_up_accrual_id"]
        assert final["amount_cents"] == -814374
        assert final["status"] == AccrualStatus.ACCRUED
        assert final["report_package_id"] == state["package_id"]

        provisional = find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)
        assert provisional["amount_cents"] == 2171253
        assert provisional["status"] == AccrualStatus.INVOICED


def _weighted_index_resort(scenario):
    """Two accepted periods, both with accepted STR benchmarks of unequal room-nights."""
    agreement = scenario.register(
        hotel_name="Weighted Index Resort",
        owner_entity_name="Comp Set Owner LP",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        gop_test_threshold_pct=0.85,
        rpi_test_threshold=90.0,
        min_benchmark_months=2,
        test_periods_expected=3,
        consecutive_failure_limit=2,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])

    september = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    bm_september = scenario.benchmark(
        september["id"],
        hotel_revpar_cents=10000,
        comp_set_revpar_cents=12000,
        rooms_available=3000,
        source=BenchmarkSource.STR_REPORT,
    )
    scenario.submit_package(september["id"])
    scenario.review_package(september["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(september["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)

    october = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=10,
        rooms_revenue_cents=21000000,
        fnb_revenue_cents=5000000,
        other_revenue_cents=1000000,
        operating_expenses_cents=6000000,
        closing_cash_available_cents=0,
    )
    bm_october = scenario.benchmark(
        october["id"],
        hotel_revpar_cents=11000,
        comp_set_revpar_cents=11500,
        rooms_available=9000,
        source=BenchmarkSource.STR_REPORT,
    )
    scenario.submit_package(october["id"])
    scenario.review_package(october["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(october["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)

    return {
        "agreement_id": agreement["id"],
        "benchmark_september_id": bm_september["id"],
        "benchmark_october_id": bm_october["id"],
    }


class TestRpiWeightedVersusSimpleAverage:
    def test_weighted_index_scores_the_test_while_the_simple_average_only_discloses(self, scenario):
        """PRD §3.7: "`rpi_weighted` is 100 multiplied by the sum across those rows of
        `hotel_revpar_cents` times `rooms_available`, divided by the sum across the same
        rows of `comp_set_revpar_cents` times `rooms_available`, rounded to two decimal
        places" and "`rpi_simple_average` is the unweighted mean of the same rows' `rpi`
        values, rounded to two decimal places; it treats every month equally and therefore
        differs from the weighted index whenever `rooms_available` varies across months. It
        is reported for comparison and must never decide the test."

        Design: Difficulty/dual_variant_calc/rpi_rooms_weighted_versus_simple_average_decides_performance_test
        """
        state = _weighted_index_resort(scenario)

        test = scenario.performance_test(state["agreement_id"], 2026)

        assert_rpi(test["rpi_weighted"], 92.47)
        assert_rpi(test["rpi_simple_average"], 89.49)
        assert test["str_month_count"] == 2

    def test_only_the_weighted_leg_decides_a_passed_covenant(self, scenario):
        """PRD §3.7: "`gop_achievement_pct` strictly below the agreement's
        `gop_test_threshold_pct`, and `rpi_weighted` strictly below the agreement's
        `rpi_test_threshold`. A figure exactly equal to either threshold passes that leg
        and so saves the test."

        Design: Difficulty/dual_variant_calc/rpi_rooms_weighted_versus_simple_average_decides_performance_test
        """
        state = _weighted_index_resort(scenario)

        test = scenario.performance_test(state["agreement_id"], 2026)

        assert test["accepted_period_count"] == 2
        assert test["budgeted_agop_snapshot_cents"] == 86500000
        assert test["budget_source_status"] == BudgetSourceStatus.APPROVED
        assert test["prorated_budget_agop_cents"] == 57666667
        assert test["actual_agop_cents"] == 40410000
        assert_gop_achievement(test["gop_achievement_pct"], 0.7008)
        # The AGOP leg is below 0.85, yet 92.47 clears the 90.0 index threshold.
        assert test["status"] == TestStatus.PASSED

    def test_passed_covenant_leaves_no_cure_obligation_and_no_failure_streak(self, scenario):
        """PRD §3.7: "Where the test does not fail, its `status` is `PASSED`,
        `streak_after_test` is 0, `cure_payment_due_cents` is 0, `cure_deadline_utc` stays
        null, and the agreement's `performance_failure_streak` is reset to 0."

        Design: Difficulty/dual_variant_calc/rpi_rooms_weighted_versus_simple_average_decides_performance_test
        """
        state = _weighted_index_resort(scenario)

        test = scenario.performance_test(state["agreement_id"], 2026)

        assert test["cure_payment_due_cents"] == 0
        assert test["cure_deadline_utc"] is None
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["performance_failure_streak"] == 0

    def test_each_benchmark_row_carries_its_own_simple_monthly_index(self, scenario):
        """PRD §3.7: "The row's index `rpi` is the hotel's revenue per available room
        divided by the competitive set's, multiplied by 100, rounded to two decimal
        places."

        Design: Difficulty/dual_variant_calc/rpi_rooms_weighted_versus_simple_average_decides_performance_test
        """
        state = _weighted_index_resort(scenario)

        packages = scenario.packages(state["agreement_id"])
        indices = {}
        for package in packages:
            for row in scenario.benchmarks(package["id"]):
                indices[row["id"]] = row["rpi"]

        assert_rpi(indices[state["benchmark_september_id"]], 83.33)
        assert_rpi(indices[state["benchmark_october_id"]], 95.65)
