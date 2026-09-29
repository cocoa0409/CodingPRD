"""Writes gated by the state of a row the acted-upon resource never names."""

from test_helpers import (
    AccrualStatus,
    AllocationBasis,
    ApiErrorId,
    BudgetDecision,
    BudgetStatus,
    DisclosureStatus,
    DistributionStatus,
    FeeType,
    FeeVariant,
    FinancialStatus,
    LedgerEntryType,
    LedgerSourceKind,
    MANAGER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    assert_error_envelope,
    assert_ledger_entry,
    assert_object_envelope,
    assert_page,
    find_accrual,
    no_rows,
)


# ---------------------------------------------------------------------------
# A package submit gated by the fiscal year's budget, reached by (agreement, year)
# ---------------------------------------------------------------------------


def _budget_gate_hotel(scenario):
    """A period ready to freeze while its fiscal year's budget is still only SUBMITTED."""
    agreement = scenario.register(
        hotel_name="Budget Gate Hotel",
        owner_entity_name="Gate Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        owner_review_window_days=30,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=1000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=600000000,
        budgeted_operating_expenses_cents=400000000,
    )
    scenario.submit_budget(budget["id"])

    package = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    return {
        "agreement_id": agreement["id"],
        "budget_id": budget["id"],
        "package_id": package["id"],
    }


class TestPackageSubmitGatedByTheYearsBudget:
    def test_submit_is_refused_while_the_years_budget_is_merely_submitted(self, scenario):
        """PRD §3.4: "Both origins require the agreement to be `ACTIVE` and both require that
        a budget of the same agreement and `fiscal_year` already holds an approved-equivalent
        status, failing which the submit is refused with `ERR_BUDGET_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/package_submit_requires_approved_budget_for_the_fiscal_year
        """
        state = _budget_gate_hotel(scenario)
        assert scenario.read_budget(state["budget_id"])["status"] == BudgetStatus.SUBMITTED

        response = scenario.api.submit_report_package(state["package_id"], MANAGER_HEADERS)

        assert_error_envelope(response, ApiErrorId.BUDGET_NOT_APPROVED)
        assert response.status_code == 422

    def test_the_refused_submit_leaves_the_period_unfrozen(self, scenario):
        """PRD §2.8 rule 40: "A budget of the same agreement and `fiscal_year` holds
        `APPROVED`, `DEEMED_APPROVED` or `DEADLOCK_CARRYFORWARD`; otherwise
        `ERR_BUDGET_NOT_APPROVED` (422)."

        Design: Difficulty/cross_entity_state_dependency/package_submit_requires_approved_budget_for_the_fiscal_year
        """
        state = _budget_gate_hotel(scenario)

        scenario.api.submit_report_package(state["package_id"], MANAGER_HEADERS)

        package = scenario.read_package(state["package_id"])
        assert package["financial_status"] == FinancialStatus.PENDING
        assert package["submitted_at"] is None
        assert_page(
            scenario.api.list_fee_accruals(state["package_id"], MANAGER_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_the_identical_submit_succeeds_once_the_sibling_budget_is_approved(self, scenario):
        """PRD §3.4: "Both origins stamp `submitted_at` with the logical clock and set
        `submitted_late` to true exactly when that instant is strictly after `due_date_utc` —
        an instant equal to the deadline is on time."

        Design: Difficulty/cross_entity_state_dependency/package_submit_requires_approved_budget_for_the_fiscal_year
        """
        state = _budget_gate_hotel(scenario)
        scenario.api.submit_report_package(state["package_id"], MANAGER_HEADERS)

        scenario.decide_budget(state["budget_id"], BudgetDecision.APPROVE)
        submitted = assert_object_envelope(
            scenario.api.submit_report_package(state["package_id"], MANAGER_HEADERS), 200
        )

        assert submitted["financial_status"] == FinancialStatus.SUBMITTED
        assert submitted["base_fee_cents"] == 1787500
        assert submitted["agop_cents"] == 23212525
        assert submitted["incentive_fee_provisional_cents"] == 2221253
        assert submitted["submitted_at"].startswith("2026-08-01T00:00:00")
        assert submitted["due_date_utc"].startswith("2026-10-25T00:00:00")
        assert submitted["submitted_late"] is False
        assert submitted["resubmission_count"] == 0


# ---------------------------------------------------------------------------
# A distribution execute gated by a sibling accrual of the same package
# ---------------------------------------------------------------------------


def _held_accrual_hotel(scenario):
    """An accepted period whose chargeback the owner side has contested."""
    agreement = scenario.register(
        hotel_name="Held Accrual Hotel",
        owner_entity_name="On Hold Owner LP",
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
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=10000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    distribution = scenario.only_distribution(package["id"])
    scenario.contest_charge(charge["id"])

    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "charge_id": charge["id"],
        "distribution_id": distribution["id"],
    }


class TestDistributionExecuteGatedByAHeldAccrual:
    def test_execute_is_refused_while_a_sibling_accrual_is_held(self, scenario):
        """PRD §3.5: "The contest has teeth: the parent package's `CENTRALIZED_SERVICES` fee
        accrual, if it sits in `ACCRUED` or `INVOICED`, is moved to `DISPUTED_HELD`, and a
        package carrying any accrual in `DISPUTED_HELD` cannot have its distribution executed
        — that attempt is refused with `ERR_ACCRUALS_ON_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/distribution_execute_blocked_by_disputed_held_accrual
        """
        state = _held_accrual_hotel(scenario)
        held = find_accrual(
            scenario.accruals(state["package_id"]),
            FeeType.CENTRALIZED_SERVICES,
            FeeVariant.PROVISIONAL,
        )
        assert held["status"] == AccrualStatus.DISPUTED_HELD

        response = scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS)

        assert_error_envelope(response, ApiErrorId.ACCRUALS_ON_HOLD)
        assert response.status_code == 409

    def test_the_refused_execute_moved_no_cash(self, scenario):
        """PRD §3.6: "Executing a distribution belongs to `HotelManagerOps` and moves it
        `CALCULATED → EXECUTED`. Three conditions guard it: the row must be `CALCULATED` — a
        `HELD` or already-`EXECUTED` row is refused with `ERR_INVALID_DISTRIBUTION_STATE` —
        the agreement's `distribution_hold` must be false, and no accrual of the same package
        may sit in `DISPUTED_HELD`."

        Design: Difficulty/cross_entity_state_dependency/distribution_execute_blocked_by_disputed_held_accrual
        """
        state = _held_accrual_hotel(scenario)

        scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS)

        distribution = scenario.only_distribution(state["package_id"])
        assert distribution["status"] == DistributionStatus.CALCULATED
        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 0
        no_rows(scenario.ledger(state["agreement_id"]))

    def test_reaffirming_the_chargeback_releases_the_held_accrual(self, scenario):
        """PRD §3.5: "moves the charge `CONTESTED → DISCLOSED` and releases the held accrual:
        it returns to `ACCRUED` when the package's `financial_status` is `SUBMITTED`, or to
        `INVOICED` when the package's `financial_status` is `ACCEPTED`, with its
        `amount_cents` rewritten to the charge's post-review allocated amount."

        Design: Difficulty/cross_entity_state_dependency/distribution_execute_blocked_by_disputed_held_accrual
        """
        state = _held_accrual_hotel(scenario)

        reaffirmed = scenario.reaffirm_charge(state["charge_id"])

        assert reaffirmed["disclosure_status"] == DisclosureStatus.DISCLOSED
        released = find_accrual(
            scenario.accruals(state["package_id"]),
            FeeType.CENTRALIZED_SERVICES,
            FeeVariant.PROVISIONAL,
        )
        assert released["status"] == AccrualStatus.INVOICED
        assert released["amount_cents"] == 500000

    def test_the_second_execute_moves_the_money_exactly_once(self, scenario):
        """PRD §3.6: "The `BASE` and `INCENTIVE` accruals of the package that received cash
        move `INVOICED → PAID`, each with `paid_amount_cents` set to the amount allocated to
        its bucket. And a reserve ledger entry is appended with `entry_type` `CONTRIBUTION`,
        `amount_cents` equal to `reserve_contribution_cents` and `source_kind`
        `DISTRIBUTION_EXECUTION`, with the agreement's `ffe_reserve_balance_cents` increased
        by the same amount"

        Design: Difficulty/cross_entity_state_dependency/distribution_execute_blocked_by_disputed_held_accrual
        """
        state = _held_accrual_hotel(scenario)
        scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS)
        scenario.reaffirm_charge(state["charge_id"])

        executed = assert_object_envelope(
            scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS), 200
        )

        assert executed["status"] == DistributionStatus.EXECUTED
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["ffe_reserve_balance_cents"] == 2200001
        # The account already sat above its 500000 floor, so wc_restoration_cents was zero.
        assert agreement["working_capital_balance_cents"] == 1000000

        entries = scenario.ledger(state["agreement_id"])
        assert len(entries) == 1
        assert_ledger_entry(
            entries[0],
            entry_type=LedgerEntryType.CONTRIBUTION,
            amount_cents=2200001,
            balance_after_cents=2200001,
            source_kind=LedgerSourceKind.DISTRIBUTION_EXECUTION,
        )

        accruals = scenario.accruals(state["package_id"])
        base = find_accrual(accruals, FeeType.BASE, FeeVariant.PROVISIONAL)
        assert base["status"] == AccrualStatus.PAID
        assert base["paid_amount_cents"] == 1787500
        incentive = find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)
        assert incentive["status"] == AccrualStatus.PAID
        assert incentive["paid_amount_cents"] == 1012499
