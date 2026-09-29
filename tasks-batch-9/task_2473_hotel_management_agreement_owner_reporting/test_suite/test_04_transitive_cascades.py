"""Multi-hop cascades where each hop fires only because the previous one changed something."""

from test_helpers import (
    AccrualStatus,
    AgreementStatus,
    AllocationBasis,
    BenchmarkSource,
    CallReason,
    CallStatus,
    DisclosureStatus,
    DistributionStatus,
    FeeType,
    FeeVariant,
    FinancialStatus,
    PackageStatus,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    TestStatus,
    assert_gop_achievement,
    assert_rpi,
    assert_waterfall,
    find_accrual,
    no_rows,
)


def _cascade_waterfall_hotel(scenario):
    """A frozen period whose demands exceed its cash, ready for the owner's acceptance."""
    agreement = scenario.register(
        hotel_name="Cascade Waterfall Hotel",
        owner_entity_name="Depth Four Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
        funding_due_days=15,
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
    scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestPackageAcceptCascade:
    def test_acceptance_invoices_every_accrued_row(self, scenario):
        """PRD §3.6: "Because the dimension became `ACCEPTED`, every fee accrual of that
        package sitting in `ACCRUED` moves to `INVOICED`, processed in `created_at` ascending
        order."

        Design: Difficulty/transitive_cascade/package_accept_cascades_accruals_distribution_and_shortfall_call
        """
        state = _cascade_waterfall_hotel(scenario)

        accepted = scenario.review_package(
            state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT
        )

        assert accepted["financial_status"] == FinancialStatus.ACCEPTED
        assert accepted["package_status"] == PackageStatus.PARTIAL

        accruals = scenario.accruals(state["package_id"])
        assert len(accruals) == 3
        assert all(row["status"] == AccrualStatus.INVOICED for row in accruals)
        assert find_accrual(accruals, FeeType.BASE, FeeVariant.PROVISIONAL)["amount_cents"] == 1787500
        assert (
            find_accrual(accruals, FeeType.CENTRALIZED_SERVICES, FeeVariant.PROVISIONAL)["amount_cents"]
            == 500000
        )
        assert (
            find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)["amount_cents"] == 2171253
        )

    def test_invoiced_accruals_create_one_partially_filled_distribution(self, scenario):
        """PRD §3.6: "Because those accruals became `INVOICED`, a `CashDistribution` row is
        created in `status` `CALCULATED` with its buckets filled by the waterfall described
        below." and "Finally `shortfall_cents` records the aggregate unmet demand: the sum of
        the five demands, less the sum of the five amounts actually allocated."

        Design: Difficulty/transitive_cascade/package_accept_cascades_accruals_distribution_and_shortfall_call
        """
        state = _cascade_waterfall_hotel(scenario)

        scenario.review_package(state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

        distribution = scenario.only_distribution(state["package_id"])
        assert distribution["status"] == DistributionStatus.CALCULATED
        assert_waterfall(
            distribution,
            available_cash_cents=6000000,
            wc_restoration_cents=0,
            base_fee_paid_cents=1787500,
            reserve_contribution_cents=2200001,
            owner_priority_paid_cents=1000000,
            incentive_fee_paid_cents=1012499,
            residual_to_owner_cents=0,
            # Total demand 7158754 against 6000000 of available cash.
            shortfall_cents=1158754,
        )

    def test_positive_shortfall_auto_raises_one_funding_call(self, scenario):
        """PRD §3.6: "Because that distribution may carry an unmet demand, a working capital
        call is raised when — and only when — its `shortfall_cents` is greater than zero: a
        call with `reason` `DISTRIBUTION_SHORTFALL`, `amount_cents` equal to the
        distribution's `shortfall_cents`, `auto_created` set to true and `status`
        `REQUESTED`."

        Design: Difficulty/transitive_cascade/package_accept_cascades_accruals_distribution_and_shortfall_call
        """
        state = _cascade_waterfall_hotel(scenario)

        scenario.review_package(state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

        call = scenario.only_call(state["agreement_id"])
        assert call["reason"] == CallReason.DISTRIBUTION_SHORTFALL
        assert call["amount_cents"] == 1158754
        assert call["auto_created"] is True
        assert call["status"] == CallStatus.REQUESTED
        # Fifteen funding days on from the epoch instant of the logical clock.
        assert call["due_date_utc"].startswith("2026-08-16T00:00:00")

    def test_calculating_the_waterfall_moves_no_cash(self, scenario):
        """PRD §3.6: "The waterfall itself is computed once, at the moment the distribution
        row is created, and its inputs are frozen there."

        Design: Difficulty/transitive_cascade/package_accept_cascades_accruals_distribution_and_shortfall_call
        """
        state = _cascade_waterfall_hotel(scenario)

        scenario.review_package(state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 0
        assert agreement["working_capital_balance_cents"] == 1000000
        no_rows(scenario.ledger(state["agreement_id"]))


def _cure_period_resort(scenario):
    """Two accepted months whose weighted index and profit both miss the covenant."""
    agreement = scenario.register(
        hotel_name="Cure Period Resort",
        owner_entity_name="Hold Release Owner LP",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        gop_test_threshold_pct=0.85,
        rpi_test_threshold=90.0,
        min_benchmark_months=2,
        test_periods_expected=3,
        consecutive_failure_limit=2,
        cure_window_days=60,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
        budgeted_capital_ffe_cents=0,
        budgeted_capital_brand_cents=0,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"])

    september = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.benchmark(
        september["id"],
        hotel_revpar_cents=10000,
        comp_set_revpar_cents=12000,
        rooms_available=9000,
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
    scenario.benchmark(
        october["id"],
        hotel_revpar_cents=11000,
        comp_set_revpar_cents=11500,
        rooms_available=3000,
        source=BenchmarkSource.STR_REPORT,
    )
    scenario.submit_package(october["id"])
    scenario.review_package(october["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(october["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)

    return {
        "agreement_id": agreement["id"],
        "september_id": september["id"],
        "october_id": october["id"],
    }


class TestCurableFailureHoldsThenReleases:
    def test_both_legs_fail_and_the_cure_obligation_is_the_profit_gap(self, scenario):
        """PRD §3.7: "Where the test does fail, `streak_after_test` is recorded as the
        agreement's `performance_failure_streak` plus one, and `cure_payment_due_cents` is
        the pro-rated budgeted profit less the actual profit, floored at zero."

        Design: Difficulty/transitive_cascade/curable_failure_holds_distributions_then_cure_releases_them
        """
        state = _cure_period_resort(scenario)

        test = scenario.performance_test(state["agreement_id"], 2026)

        assert_rpi(test["rpi_weighted"], 86.32)
        assert_rpi(test["rpi_simple_average"], 89.49)
        assert_gop_achievement(test["gop_achievement_pct"], 0.7008)
        assert test["prorated_budget_agop_cents"] == 57666667
        assert test["status"] == TestStatus.FAILED_CURABLE
        assert test["cure_payment_due_cents"] == 17256667
        assert test["cure_deadline_utc"].startswith("2026-09-30T00:00:00")

    def test_curable_failure_holds_every_calculated_distribution(self, scenario):
        """PRD §3.7: "the agreement moves `ACTIVE → CURE_PERIOD`, which in turn increments
        `performance_failure_streak` by one, sets `distribution_hold` to true because the
        status became `CURE_PERIOD`, and — because the hold went up — moves every
        `CALCULATED` distribution of that agreement to `HELD` in `created_at` ascending
        order."

        Design: Difficulty/transitive_cascade/curable_failure_holds_distributions_then_cure_releases_them
        """
        state = _cure_period_resort(scenario)

        scenario.performance_test(state["agreement_id"], 2026)

        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.CURE_PERIOD
        assert agreement["performance_failure_streak"] == 1
        assert agreement["distribution_hold"] is True
        assert scenario.only_distribution(state["september_id"])["status"] == DistributionStatus.HELD
        assert scenario.only_distribution(state["october_id"])["status"] == DistributionStatus.HELD

    def test_paid_cure_unwinds_the_same_three_hops(self, scenario):
        """PRD §3.7: "A sufficient payment writes `cure_paid_cents` as the amount paid and
        returns the agreement `CURE_PERIOD → ACTIVE`, which resets
        `performance_failure_streak` to 0, increases `working_capital_balance_cents` by the
        amount actually paid, sets `distribution_hold` to false, and — because the hold came
        down — returns every `HELD` distribution of the agreement to `CALCULATED` in
        `created_at` ascending order with bucket amounts untouched."

        Design: Difficulty/transitive_cascade/curable_failure_holds_distributions_then_cure_releases_them
        """
        state = _cure_period_resort(scenario)
        test = scenario.performance_test(state["agreement_id"], 2026)
        scenario.elect_cure(test["id"])

        cured = scenario.pay_cure(test["id"], 17256667)

        assert cured["status"] == TestStatus.CURED
        assert cured["cure_paid_cents"] == 17256667
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["distribution_hold"] is False
        assert agreement["performance_failure_streak"] == 0
        assert agreement["working_capital_balance_cents"] == 17256667

    def test_released_distribution_keeps_its_bucket_amounts(self, scenario):
        """PRD §3.6: "A `HELD` row that later returns to `CALCULATED` keeps its bucket
        amounts exactly as computed — the waterfall is never recalculated on release."

        Design: Difficulty/transitive_cascade/curable_failure_holds_distributions_then_cure_releases_them
        """
        state = _cure_period_resort(scenario)
        test = scenario.performance_test(state["agreement_id"], 2026)
        scenario.elect_cure(test["id"])
        scenario.pay_cure(test["id"], 17256667)

        distribution = scenario.only_distribution(state["september_id"])
        assert distribution["status"] == DistributionStatus.CALCULATED
        assert_waterfall(
            distribution,
            available_cash_cents=0,
            wc_restoration_cents=0,
            base_fee_paid_cents=0,
            reserve_contribution_cents=0,
            owner_priority_paid_cents=0,
            incentive_fee_paid_cents=0,
            residual_to_owner_cents=0,
            # Nothing was ever allocated, so the whole 4742000 of demand stands unmet.
            shortfall_cents=4742000,
        )


def _chargeback_transparency_hotel(scenario):
    """A frozen period whose single chargeback has been contested by the owner side."""
    agreement = scenario.register(
        hotel_name="Chargeback Transparency Hotel",
        owner_entity_name="Adjust Cascade Owner LLC",
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
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    scenario.contest_charge(charge["id"])
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "charge_id": charge["id"],
    }


class TestChargebackAdjustmentCascade:
    def test_adjustment_rewrites_the_allocated_and_deferred_amounts(self, scenario):
        """PRD §3.5: "First, the charge's `allocated_amount_cents` is replaced by
        `adjusted_amount_cents` and its `deferred_amount_cents` is recomputed as its
        `requested_amount_cents` less the new allocated amount."

        Design: Difficulty/transitive_cascade/chargeback_adjustment_recomputes_agop_and_rewrites_incentive_accrual
        """
        state = _chargeback_transparency_hotel(scenario)

        adjusted = scenario.adjust_charge(state["charge_id"], 200000)

        assert adjusted["disclosure_status"] == DisclosureStatus.ADJUSTED
        assert adjusted["adjusted_amount_cents"] == 200000
        assert adjusted["allocated_amount_cents"] == 200000
        assert adjusted["deferred_amount_cents"] == 300000
        assert adjusted["requested_amount_cents"] == 500000

    def test_smaller_chargeback_re_derives_the_package_profit(self, scenario):
        """PRD §3.5: "Second, because the charge's allocated amount changed, the package's
        `allocated_centralized_cents`, its `agop_cents` and its
        `incentive_fee_provisional_cents` are all recomputed by the same pinned five-step
        order described in §3.4 — a smaller chargeback means a larger adjusted gross
        operating profit and therefore a larger provisional incentive fee."

        Design: Difficulty/transitive_cascade/chargeback_adjustment_recomputes_agop_and_rewrites_incentive_accrual
        """
        state = _chargeback_transparency_hotel(scenario)
        before = scenario.read_package(state["package_id"])
        assert before["agop_cents"] == 22712525

        scenario.adjust_charge(state["charge_id"], 200000)

        package = scenario.read_package(state["package_id"])
        assert package["allocated_centralized_cents"] == 200000
        assert package["agop_cents"] == 23012525
        assert package["incentive_fee_provisional_cents"] == 2201253
        assert package["base_fee_cents"] == 1787500
        assert package["gross_revenue_cents"] == 55000025

    def test_posted_accruals_are_rewritten_in_place_and_released(self, scenario):
        """PRD §3.5: "Third, because the package's provisional incentive changed, the
        package's `INCENTIVE` accrual of `variant` `PROVISIONAL` has its `amount_cents`
        rewritten to the new value, and the `CENTRALIZED_SERVICES` accrual has its
        `amount_cents` rewritten to the adjusted amount and is returned from `DISPUTED_HELD`
        to whichever status it held before the contest — `ACCRUED` if the package's
        `financial_status` is `SUBMITTED`, `INVOICED` if it is `ACCEPTED`."

        Design: Difficulty/transitive_cascade/chargeback_adjustment_recomputes_agop_and_rewrites_incentive_accrual
        """
        state = _chargeback_transparency_hotel(scenario)

        scenario.adjust_charge(state["charge_id"], 200000)

        accruals = scenario.accruals(state["package_id"])
        incentive = find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)
        assert incentive["amount_cents"] == 2201253
        assert incentive["status"] == AccrualStatus.ACCRUED
        centralized = find_accrual(accruals, FeeType.CENTRALIZED_SERVICES, FeeVariant.PROVISIONAL)
        assert centralized["amount_cents"] == 200000
        assert centralized["status"] == AccrualStatus.ACCRUED
        no_rows(scenario.distributions(state["package_id"]))
