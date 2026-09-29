"""State machines with cycles, exhaustion branches and parallel dimensions."""

from test_helpers import (
    AccrualStatus,
    BenchmarkStatus,
    BudgetDecision,
    BudgetStatus,
    DistributionStatus,
    DisputeStatus,
    FeeType,
    FeeVariant,
    FinancialStatus,
    FundingSource,
    LedgerEntryType,
    LedgerSourceKind,
    PackageStatus,
    ReviewDecision,
    ReviewDimension,
    assert_rpi,
    find_accrual,
    rows_where,
)


def _deadlock_carryforward_lodge(scenario):
    """A FY2026 budget already back in SUBMITTED with one revision round spent."""
    agreement = scenario.register(
        hotel_name="Deadlock Carryforward Lodge",
        owner_entity_name="Carryforward Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
        max_revision_rounds=1,
        owner_review_window_days=30,
    )
    scenario.activate(agreement["id"])

    prior_year = scenario.budget(
        agreement["id"],
        fiscal_year=2025,
        budgeted_revenue_cents=500000000,
        budgeted_operating_expenses_cents=330000000,
        budgeted_capital_ffe_cents=15000000,
        budgeted_capital_brand_cents=8000000,
    )
    scenario.submit_budget(prior_year["id"])
    scenario.decide_budget(prior_year["id"], BudgetDecision.APPROVE)

    current_year = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=620000000,
        budgeted_operating_expenses_cents=410000000,
        budgeted_capital_ffe_cents=21000000,
        budgeted_capital_brand_cents=11000000,
    )
    scenario.submit_budget(current_year["id"])
    scenario.decide_budget(current_year["id"], BudgetDecision.REQUEST_REVISION)
    scenario.submit_budget(
        current_year["id"],
        budgeted_revenue_cents=618000000,
        budgeted_operating_expenses_cents=408000000,
        budgeted_capital_ffe_cents=21000000,
        budgeted_capital_brand_cents=11000000,
    )
    return {
        "agreement_id": agreement["id"],
        "prior_year_id": prior_year["id"],
        "current_year_id": current_year["id"],
    }


class TestBudgetRevisionCycleExhaustion:
    def test_second_revision_request_deadlocks_instead_of_repeating(self, scenario):
        """PRD §3.2: "When `revision_round` has reached or passed `max_revision_rounds`, a
        further revision request deadlocks: the row moves `SUBMITTED →
        DEADLOCK_CARRYFORWARD`, `carryforward_applied` is set to true"

        Design: Difficulty/non_linear_state_machine/budget_revision_cycle_exhausts_rounds_and_deadlocks_into_carryforward
        """
        state = _deadlock_carryforward_lodge(scenario)

        deadlocked = scenario.decide_budget(
            state["current_year_id"], BudgetDecision.REQUEST_REVISION
        )

        assert deadlocked["status"] == BudgetStatus.DEADLOCK_CARRYFORWARD
        assert deadlocked["status"] != BudgetStatus.REVISION_REQUESTED
        assert deadlocked["revision_round"] == 1
        assert deadlocked["carryforward_applied"] is True

    def test_deadlock_overwrites_all_four_amounts_at_the_carry_forward_factor(self, scenario):
        """PRD §3.2: "Each of the source's `budgeted_revenue_cents`,
        `budgeted_operating_expenses_cents`, `budgeted_capital_ffe_cents` and
        `budgeted_capital_brand_cents` is multiplied by a carry-forward factor of 1.03 — a
        three percent uplift — and rounded half up to whole cents, and the result overwrites
        the corresponding field on the deadlocked row."

        Design: Difficulty/non_linear_state_machine/budget_revision_cycle_exhausts_rounds_and_deadlocks_into_carryforward
        """
        state = _deadlock_carryforward_lodge(scenario)

        scenario.decide_budget(state["current_year_id"], BudgetDecision.REQUEST_REVISION)

        budget = scenario.read_budget(state["current_year_id"])
        assert budget["budgeted_revenue_cents"] == 515000000
        assert budget["budgeted_operating_expenses_cents"] == 339900000
        assert budget["budgeted_capital_ffe_cents"] == 15450000
        assert budget["budgeted_capital_brand_cents"] == 8240000

    def test_derived_amounts_are_recomputed_from_the_carried_forward_figures(self, scenario):
        """PRD §3.2: "Either way, `budgeted_base_fee_cents`, `budgeted_centralized_cents`
        and `budgeted_agop_cents` are then recomputed from whatever amounts now stand."

        Design: Difficulty/non_linear_state_machine/budget_revision_cycle_exhausts_rounds_and_deadlocks_into_carryforward
        """
        state = _deadlock_carryforward_lodge(scenario)

        scenario.decide_budget(state["current_year_id"], BudgetDecision.REQUEST_REVISION)

        budget = scenario.read_budget(state["current_year_id"])
        assert budget["budgeted_base_fee_cents"] == 16737500
        assert budget["budgeted_centralized_cents"] == 7725000
        assert budget["budgeted_agop_cents"] == 150637500

    def test_prior_year_source_budget_is_left_exactly_as_it_stood(self, scenario):
        """PRD §3.2: "An approval moves the row `SUBMITTED → APPROVED` and records
        `decided_by_user_id` as the acting `X-User-ID`; that is its entire effect."

        Design: Difficulty/non_linear_state_machine/budget_revision_cycle_exhausts_rounds_and_deadlocks_into_carryforward
        """
        state = _deadlock_carryforward_lodge(scenario)

        scenario.decide_budget(state["current_year_id"], BudgetDecision.REQUEST_REVISION)

        prior = scenario.read_budget(state["prior_year_id"])
        assert prior["status"] == BudgetStatus.APPROVED
        assert prior["budgeted_revenue_cents"] == 500000000
        assert prior["budgeted_operating_expenses_cents"] == 330000000
        assert prior["budgeted_capital_ffe_cents"] == 15000000
        assert prior["budgeted_capital_brand_cents"] == 8000000


def _two_dimension_tower(scenario):
    """A package with the financial dimension ACCEPTED and the benchmark SUBMITTED."""
    agreement = scenario.register(
        hotel_name="Two Dimension Tower",
        owner_entity_name="Parallel Dim Owner LP",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
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
    benchmark = scenario.benchmark(
        package["id"], hotel_revpar_cents=10000, comp_set_revpar_cents=12000, rooms_available=3000
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "benchmark_id": benchmark["id"],
    }


class TestPackageStatusDimensionsAdvanceIndependently:
    def test_benchmark_challenge_leaves_the_financial_dimension_accepted(self, scenario):
        """PRD §3.6: "The named dimension advances; the other is left exactly as it was."

        Design: Difficulty/non_linear_state_machine/report_package_two_status_dimensions_advance_independently
        """
        state = _two_dimension_tower(scenario)
        before = scenario.read_package(state["package_id"])
        assert before["package_status"] == PackageStatus.PARTIAL

        scenario.review_package(
            state["package_id"], ReviewDimension.BENCHMARK, ReviewDecision.DISPUTE
        )

        after = scenario.read_package(state["package_id"])
        assert after["benchmark_status"] == BenchmarkStatus.CHALLENGED
        assert after["financial_status"] == FinancialStatus.ACCEPTED

    def test_roll_up_flips_from_partial_to_contested(self, scenario):
        """PRD §3.4: "If `financial_status` is `DISPUTED` or `benchmark_status` is
        `CHALLENGED`, the roll-up is `CONTESTED`."

        Design: Difficulty/non_linear_state_machine/report_package_two_status_dimensions_advance_independently
        """
        state = _two_dimension_tower(scenario)

        scenario.review_package(
            state["package_id"], ReviewDimension.BENCHMARK, ReviewDecision.DISPUTE
        )

        package = scenario.read_package(state["package_id"])
        assert package["package_status"] == PackageStatus.CONTESTED
        assert_rpi(package["reported_rpi"], 83.33)
        benchmark = next(
            row for row in scenario.benchmarks(state["package_id"]) if row["id"] == state["benchmark_id"]
        )
        assert benchmark["superseded"] is False

    def test_benchmark_challenge_reverses_no_accrual_and_holds_no_distribution(self, scenario):
        """PRD §3.6: "every fee accrual of that package sitting in `ACCRUED` moves to
        `INVOICED`, processed in `created_at` ascending order. Because those accruals became
        `INVOICED`, a `CashDistribution` row is created in `status` `CALCULATED`"

        Design: Difficulty/non_linear_state_machine/report_package_two_status_dimensions_advance_independently
        """
        state = _two_dimension_tower(scenario)

        scenario.review_package(
            state["package_id"], ReviewDimension.BENCHMARK, ReviewDecision.DISPUTE
        )

        accruals = scenario.accruals(state["package_id"])
        # No centralized chargeback was posted, so that accrual was omitted entirely.
        assert len(rows_where(accruals, fee_type=FeeType.CENTRALIZED_SERVICES)) == 0
        assert len(accruals) == 2
        assert all(row["status"] == AccrualStatus.INVOICED for row in accruals)
        assert find_accrual(accruals, FeeType.BASE, FeeVariant.PROVISIONAL)["amount_cents"] == 1787500
        assert (
            find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)["amount_cents"]
            == 2221253
        )

        distribution = scenario.only_distribution(state["package_id"])
        assert distribution["status"] == DistributionStatus.CALCULATED


def _brand_standard_cycle_hotel(scenario):
    """A dispute settled from the reserve, with the reserve funded by one execution."""
    agreement = scenario.register(
        hotel_name="Brand Standard Cycle Hotel",
        owner_entity_name="Rescind Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        centralized_services_cap_pct=0.015,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
        max_dispute_rounds=1,
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
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    distribution = scenario.only_distribution(package["id"])
    scenario.execute_distribution(distribution["id"])

    dispute = scenario.dispute(agreement["id"])
    scenario.manager_response(dispute["id"], 1500000)
    scenario.owner_counter(dispute["id"], 1200000)
    scenario.resolve_owner_funds(dispute["id"], FundingSource.FFE_RESERVE)
    return {"agreement_id": agreement["id"], "dispute_id": dispute["id"]}


class TestBrandDisputeRescissionCycle:
    def test_rescission_reopens_negotiation_with_the_round_count_preserved(self, scenario):
        """PRD §3.9: "A `RESCIND_RESOLUTION` action by `OwnerRep` moves
        `RESOLVED_OWNER_FUNDS → OWNER_COUNTERED`, returning the dispute to live
        negotiation." and "In every case `funded_amount_cents` is reset to zero and
        `funding_source` is reset to null, while `round` is left unchanged — rescinding does
        not rewind the negotiation count."

        Design: Difficulty/non_linear_state_machine/brand_dispute_rescission_reopens_negotiation_cycle_then_waives
        """
        state = _brand_standard_cycle_hotel(scenario)

        rescinded = scenario.rescind(state["dispute_id"])

        assert rescinded["status"] == DisputeStatus.OWNER_COUNTERED
        assert rescinded["round"] == 1
        assert rescinded["funded_amount_cents"] == 0
        assert rescinded["funding_source"] is None

    def test_rescission_returns_the_reserve_to_exactly_where_it_stood(self, scenario):
        """PRD §3.9: "rescission appends a compensating reserve ledger entry with
        `entry_type` `DISBURSEMENT_REVERSAL`, `amount_cents` equal to the positive
        `funded_amount_cents` and `source_kind` `BRAND_DISPUTE_RESCISSION`, and increases
        `ffe_reserve_balance_cents` by that amount, so the reserve returns to exactly where
        it stood."

        Design: Difficulty/non_linear_state_machine/brand_dispute_rescission_reopens_negotiation_cycle_then_waives
        """
        state = _brand_standard_cycle_hotel(scenario)
        funded = scenario.read_agreement(state["agreement_id"])
        assert funded["ffe_reserve_balance_cents"] == 1000001

        scenario.rescind(state["dispute_id"])

        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 2200001
        entries = scenario.ledger(state["agreement_id"])
        assert len(entries) == 3
        assert [row["entry_type"] for row in entries] == [
            LedgerEntryType.CONTRIBUTION,
            LedgerEntryType.DISBURSEMENT,
            LedgerEntryType.DISBURSEMENT_REVERSAL,
        ]
        assert entries[2]["amount_cents"] == 1200000
        assert entries[2]["source_kind"] == LedgerSourceKind.BRAND_DISPUTE_RESCISSION

    def test_second_negotiation_lap_ends_in_a_waiver_at_round_two(self, scenario):
        """PRD §3.9: "A further `MANAGER_RESPONSE` moves `OWNER_COUNTERED →
        MANAGER_RESPONDED` and again replaces `current_cost_estimate_cents` without touching
        `round`, so the pair may cycle indefinitely with `round` advancing once per full
        turn." and "A `RESOLVE_WAIVED` action by `OwnerRep` from `MANAGER_RESPONDED`, or the
        same action from `OWNER_COUNTERED`, moves the dispute to `RESOLVED_WAIVED` with no
        cash movement in either case"

        Design: Difficulty/non_linear_state_machine/brand_dispute_rescission_reopens_negotiation_cycle_then_waives
        """
        state = _brand_standard_cycle_hotel(scenario)
        scenario.rescind(state["dispute_id"])

        scenario.manager_response(state["dispute_id"], 1100000)
        scenario.owner_counter(state["dispute_id"], 900000)
        waived = scenario.resolve_waived(state["dispute_id"])

        assert waived["status"] == DisputeStatus.RESOLVED_WAIVED
        assert waived["round"] == 2
        assert waived["current_cost_estimate_cents"] == 900000
        assert waived["funded_amount_cents"] == 0
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 2200001
        assert len(scenario.ledger(state["agreement_id"])) == 3
