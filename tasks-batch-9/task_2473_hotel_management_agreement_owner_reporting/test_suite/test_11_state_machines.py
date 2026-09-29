"""Declared transitions, initial states, terminal lockdown and the branch side effects."""

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    AccrualStatus,
    AgreementStatus,
    ApiErrorId,
    ApprovalLevel,
    BenchmarkStatus,
    BudgetDecision,
    BudgetStatus,
    CallReason,
    CallStatus,
    DistributionStatus,
    FeeType,
    FeeVariant,
    FinancialStatus,
    MANAGER_HEADERS,
    PackageStatus,
    ReviewDecision,
    ReviewDimension,
    TestStatus,
    VarianceCategory,
    VarianceStatus,
    assert_error_envelope,
    assert_gop_achievement,
    assert_object_envelope,
    assert_page,
    assert_rpi,
    budget_submit_payload,
    find_accrual,
    package_payload,
    working_capital_call_payload,
)


# ---------------------------------------------------------------------------
# DRAFT -> ACTIVE: the one moment the opening deposit is recognised
# ---------------------------------------------------------------------------


class TestAgreementActivation:
    def test_activation_funds_the_opening_working_capital_and_bumps_the_version(self, scenario):
        """PRD §3.1: "Activation is the `PlatformAdmin`'s second act and is permitted only while
        the agreement is `DRAFT`. It moves the agreement `DRAFT → ACTIVE`, writes
        `initial_working_capital_cents` into `working_capital_balance_cents` — this is the only
        moment the opening deposit is recognised — sets `distribution_hold` to false, and
        increments the agreement's `version` by one."

        Design: Corner/state_machines/agreement_activate_moves_draft_to_active_and_funds_working_capital
        """
        draft = scenario.register(
            hotel_name="Activate Hotel",
            owner_entity_name="Activate Owner LLC",
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
            initial_working_capital_cents=1000000,
            working_capital_floor_cents=500000,
        )
        assert draft["status"] == AgreementStatus.DRAFT
        assert draft["working_capital_balance_cents"] == 0
        assert draft["version"] == 1

        activated = assert_object_envelope(
            scenario.api.activate_agreement(draft["id"], ADMIN_HEADERS), 200
        )

        assert activated["status"] == AgreementStatus.ACTIVE
        assert activated["working_capital_balance_cents"] == 1000000
        assert activated["distribution_hold"] is False
        assert activated["version"] == 2


# ---------------------------------------------------------------------------
# An origin the submit transition does not declare
# ---------------------------------------------------------------------------


def _invalid_from_hotel(scenario):
    """An APPROVED FY2026 budget, which submit does not declare as an origin."""
    agreement = scenario.register(
        hotel_name="Invalid From Hotel",
        owner_entity_name="From State Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestBudgetSubmitFromAnUndeclaredOrigin:
    def test_resubmitting_an_approved_budget_is_refused(self, scenario):
        """PRD §3.2: "Submission is available to `HotelManagerOps` from `DRAFT → SUBMITTED` and
        from `REVISION_REQUESTED → SUBMITTED`, and in both cases the agreement must be `ACTIVE`."
        PRD §2.8 rule 20: "The budget's `status` is one the requested transition declares as its
        origin; otherwise `ERR_INVALID_BUDGET_STATE` (409). Applies to
        `POST /hotel-management/budgets/{id}/submit` and
        `POST /hotel-management/budgets/{id}/decision`."

        Design: Corner/state_machines/budget_submit_from_approved_state_rejected
        """
        state = _invalid_from_hotel(scenario)

        response = scenario.api.submit_budget(
            state["budget_id"],
            MANAGER_HEADERS,
            budget_submit_payload(budgeted_revenue_cents=320000000),
        )

        assert_error_envelope(response, ApiErrorId.INVALID_BUDGET_STATE)
        assert response.status_code == 409

    def test_the_refused_submit_rewrote_none_of_the_frozen_amounts(self, scenario):
        """PRD §3.2: "The budgeted adjusted gross operating profit, `budgeted_agop_cents`, is the
        budgeted gross revenue less the budgeted operating expenses, less the budgeted base fee,
        less the budgeted centralized charge." And "The `REVISION_REQUESTED` origin additionally
        increments `revision_round` by one; the `DRAFT` origin does not, leaving `revision_round`
        at its opening value of 0."

        Design: Corner/state_machines/budget_submit_from_approved_state_rejected
        """
        state = _invalid_from_hotel(scenario)

        scenario.api.submit_budget(
            state["budget_id"],
            MANAGER_HEADERS,
            budget_submit_payload(budgeted_revenue_cents=320000000),
        )

        budget = scenario.read_budget(state["budget_id"])
        assert budget["status"] == BudgetStatus.APPROVED
        assert budget["budgeted_revenue_cents"] == 300000000
        assert budget["revision_round"] == 0
        # 300000000 - 200000000 - 9000000 - 4500000.
        assert budget["budgeted_agop_cents"] == 86500000


# ---------------------------------------------------------------------------
# The initial state of a freshly opened period
# ---------------------------------------------------------------------------


class TestReportPackageInitialState:
    def test_a_freshly_opened_period_is_pending_on_both_dimensions(self, scenario):
        """PRD §3.4: "A freshly opened package sits at `financial_status` `PENDING`,
        `benchmark_status` `PENDING` and `package_status` `INCOMPLETE`, with `submitted_at` null,
        `submitted_late` false, `resubmission_count` at 0, `reported_rpi` null, and
        `allocated_centralized_cents`, `base_fee_cents`, `agop_cents` and
        `incentive_fee_provisional_cents` all at 0."

        Design: Corner/state_machines/report_package_initial_state_is_pending_on_both_dimensions
        """
        agreement = scenario.register(
            hotel_name="Initial State Hotel",
            owner_entity_name="Initial Owner LLC",
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
        )
        scenario.activate(agreement["id"])

        package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)

        assert package["financial_status"] == FinancialStatus.PENDING
        assert package["benchmark_status"] == BenchmarkStatus.PENDING
        assert package["package_status"] == PackageStatus.INCOMPLETE
        assert package["submitted_at"] is None
        assert package["submitted_late"] is False
        assert package["resubmission_count"] == 0
        assert package["reported_rpi"] is None

    def test_no_accrual_exists_before_the_period_is_submitted(self, scenario):
        """PRD §3.4: "Each submit raises a fresh set of fee accruals in `ACCRUED`: a `BASE`
        accrual of `variant` `PROVISIONAL` carrying `base_fee_cents`; a `CENTRALIZED_SERVICES`
        accrual of `variant` `PROVISIONAL` carrying `allocated_centralized_cents`, omitted
        entirely when that amount is zero; and an `INCENTIVE` accrual of `variant` `PROVISIONAL`
        carrying `incentive_fee_provisional_cents`, likewise omitted when zero."

        Design: Corner/state_machines/report_package_initial_state_is_pending_on_both_dimensions
        """
        agreement = scenario.register(
            hotel_name="Initial State Hotel",
            owner_entity_name="Initial Owner LLC",
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
        )
        scenario.activate(agreement["id"])

        package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)

        assert package["base_fee_cents"] == 0
        assert package["agop_cents"] == 0
        assert package["incentive_fee_provisional_cents"] == 0
        assert package["allocated_centralized_cents"] == 0
        assert_page(
            scenario.api.list_fee_accruals(package["id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# The terminal state: the clock finishes the job and the doors close
# ---------------------------------------------------------------------------


def _terminal_lockdown_hotel(scenario):
    """One accepted period that fails both covenant legs on a one-strike agreement."""
    agreement = scenario.register(
        hotel_name="Terminal Lockdown Hotel",
        owner_entity_name="Terminal Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
        gop_test_threshold_pct=0.85,
        rpi_test_threshold=90.0,
        min_benchmark_months=1,
        test_periods_expected=1,
        consecutive_failure_limit=1,
        termination_notice_days=1,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.benchmark(package["id"])
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    test = scenario.performance_test(agreement["id"], 2026)

    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "test_id": test["id"],
    }


class TestTerminatedAgreementLockdown:
    def test_the_notice_moves_the_test_to_its_terminal_outcome(self, scenario):
        """PRD §3.7: "If the new streak has reached or passed the limit, the test lands in
        `TERMINATION_TRIGGERED`: the agreement's `performance_failure_streak` is incremented by
        one, `cure_deadline_utc` stays null because no cure right arises at all, and the
        agreement's `status` stays `ACTIVE` until the owner chooses to issue notice." And
        "Issuing that notice belongs to `OwnerRep`, may carry an optional `reason`, and requires
        a test in `TERMINATION_TRIGGERED` with the agreement in `ACTIVE` or `CURE_PERIOD`; it
        moves the test `TERMINATION_TRIGGERED → TERMINATED_NOTICE_ISSUED`."

        Design: Corner/state_machines/terminated_agreement_refuses_further_operational_writes
        """
        state = _terminal_lockdown_hotel(scenario)

        noticed = scenario.terminate_test(state["test_id"])

        assert noticed["status"] == TestStatus.TERMINATED_NOTICE_ISSUED
        assert noticed["prorated_budget_agop_cents"] == 86500000
        assert noticed["actual_agop_cents"] == 20220000
        assert_gop_achievement(noticed["gop_achievement_pct"], 0.2338)
        assert_rpi(noticed["rpi_weighted"], 83.33)
        assert noticed["cure_deadline_utc"] is None

    def test_the_clock_sweep_drives_the_noticed_agreement_into_termination(self, scenario):
        """PRD §2.10: "Every agreement in `TERMINATION_NOTICED` whose `termination_effective_utc`
        is at or before the new clock value becomes `TERMINATED`. The count is reported as
        `terminated_agreement_count`." PRD §3.7: "Once notice is out, only the clock can finish
        the job: when it reaches or passes `termination_effective_utc`, the agreement moves
        `TERMINATION_NOTICED → TERMINATED`, `distribution_hold` stays true, and no further
        operational write is accepted."

        Design: Corner/state_machines/terminated_agreement_refuses_further_operational_writes
        """
        state = _terminal_lockdown_hotel(scenario)
        scenario.terminate_test(state["test_id"])
        noticed = scenario.read_agreement(state["agreement_id"])
        assert noticed["status"] == AgreementStatus.TERMINATION_NOTICED
        # PRD §3.7: the clock at the notice advanced by `termination_notice_days` of 1.
        assert noticed["termination_effective_utc"].startswith("2026-08-02T00:00:00")

        sweep = scenario.set_clock("2026-08-02T00:00:00Z")

        assert sweep["terminated_agreement_count"] == 1
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.TERMINATED
        assert agreement["distribution_hold"] is True

    def test_the_terminated_agreement_refuses_both_operational_writes(self, scenario):
        """PRD §2.8 rule 18: "The agreement's `status` is `ACTIVE`; otherwise
        `ERR_AGREEMENT_NOT_ACTIVE` (409)." PRD §3.1: "Any of the twelve operational writes listed
        as rule 18 in §2.8 attempted while the agreement sits in `DRAFT`, `CURE_PERIOD`,
        `TERMINATION_NOTICED` or `TERMINATED` is refused with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/state_machines/terminated_agreement_refuses_further_operational_writes
        """
        state = _terminal_lockdown_hotel(scenario)
        scenario.terminate_test(state["test_id"])
        scenario.set_clock("2026-08-02T00:00:00Z")

        opened = scenario.api.create_report_package(
            state["agreement_id"],
            package_payload(
                fiscal_year=2026,
                period_month=10,
                rooms_revenue_cents=21000000,
                operating_expenses_cents=6000000,
            ),
            MANAGER_HEADERS,
        )
        called = scenario.api.create_working_capital_call(
            state["agreement_id"],
            working_capital_call_payload(
                amount_cents=500000, reason=CallReason.FLOOR_RESTORATION
            ),
            MANAGER_HEADERS,
        )

        assert_error_envelope(opened, ApiErrorId.AGREEMENT_NOT_ACTIVE)
        assert opened.status_code == 409
        assert_error_envelope(called, ApiErrorId.AGREEMENT_NOT_ACTIVE)
        assert called.status_code == 409

        # Neither rejected write left a row behind: one period, and only the
        # DISTRIBUTION_SHORTFALL call the acceptance raised automatically.
        assert_page(
            scenario.api.list_report_packages(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        rows = assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["reason"] == CallReason.DISTRIBUTION_SHORTFALL
        assert rows[0]["amount_cents"] == 3702000


# ---------------------------------------------------------------------------
# The submit transition's own precondition on the parent agreement
# ---------------------------------------------------------------------------


def _precondition_hotel(scenario):
    """A DRAFT FY2027 budget on an agreement the covenant pushed into CURE_PERIOD."""
    agreement = scenario.register(
        hotel_name="Precondition Hotel",
        owner_entity_name="Precondition Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
        min_benchmark_months=1,
        test_periods_expected=1,
        consecutive_failure_limit=2,
        cure_window_days=60,
    )
    scenario.activate(agreement["id"])
    budget_2026 = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget_2026["id"])
    scenario.decide_budget(budget_2026["id"], BudgetDecision.APPROVE)

    budget_2027 = scenario.budget(
        agreement["id"],
        fiscal_year=2027,
        budgeted_revenue_cents=310000000,
        budgeted_operating_expenses_cents=205000000,
    )

    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.benchmark(package["id"])
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    test = scenario.performance_test(agreement["id"], 2026)

    return {
        "agreement_id": agreement["id"],
        "budget_2027_id": budget_2027["id"],
        "test_status": test["status"],
    }


class TestBudgetSubmitRequiresAnActiveAgreement:
    def test_submit_is_refused_while_the_agreement_sits_in_cure_period(self, scenario):
        """PRD §3.7: "If the new streak is still strictly below the limit, the test lands in
        `FAILED_CURABLE`: `cure_deadline_utc` is set to the scoring instant advanced by the
        agreement's `cure_window_days`, and the agreement moves `ACTIVE → CURE_PERIOD`" PRD §3.2:
        "Submission is available to `HotelManagerOps` from `DRAFT → SUBMITTED` and from
        `REVISION_REQUESTED → SUBMITTED`, and in both cases the agreement must be `ACTIVE`."

        Design: Corner/state_machines/budget_submit_requires_active_agreement
        """
        state = _precondition_hotel(scenario)
        assert state["test_status"] == TestStatus.FAILED_CURABLE
        assert (
            scenario.read_agreement(state["agreement_id"])["status"]
            == AgreementStatus.CURE_PERIOD
        )

        response = scenario.api.submit_budget(state["budget_2027_id"], MANAGER_HEADERS)

        assert_error_envelope(response, ApiErrorId.AGREEMENT_NOT_ACTIVE)
        assert response.status_code == 409

    def test_the_refused_submit_left_the_budget_unstamped(self, scenario):
        """PRD §3.2: "Both origins stamp `submitted_at` with the logical clock, stamp
        `submitted_by_user_id` with the acting `X-User-ID`, and set `owner_decision_deadline_utc`
        to `submitted_at` advanced by the agreement's `owner_review_window_days`."

        Design: Corner/state_machines/budget_submit_requires_active_agreement
        """
        state = _precondition_hotel(scenario)

        scenario.api.submit_budget(state["budget_2027_id"], MANAGER_HEADERS)

        budget = scenario.read_budget(state["budget_2027_id"])
        assert budget["status"] == BudgetStatus.DRAFT
        assert budget["submitted_at"] is None
        assert budget["submitted_by_user_id"] is None
        assert budget["owner_decision_deadline_utc"] is None


# ---------------------------------------------------------------------------
# The DISPUTE branch of the financial dimension: everything unwinds
# ---------------------------------------------------------------------------


def _dispute_branch_hotel(scenario):
    """A SUBMITTED September period carrying a BASE and an INCENTIVE accrual."""
    agreement = scenario.register(
        hotel_name="Dispute Branch Hotel",
        owner_entity_name="Dispute Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
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
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(package["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestFinancialDisputeUnwindsThePeriod:
    def test_the_dispute_reverses_every_accrued_row_and_moves_no_cash(self, scenario):
        """PRD §3.6: "every fee accrual of the package sitting in `ACCRUED` moves to `REVERSED`,
        processed in `created_at` ascending order; no `CashDistribution` row is created; no
        reserve movement is posted; and no working capital call is raised. A reversed accrual
        keeps its `amount_cents` for audit but stops contributing to any waterfall demand or
        annual sum."

        Design: Corner/state_machines/financial_dispute_reverses_accruals_and_creates_no_distribution
        """
        state = _dispute_branch_hotel(scenario)

        scenario.review_package(
            state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.DISPUTE
        )

        reversed_rows = assert_page(
            scenario.api.list_fee_accruals(
                state["package_id"], ASSET_HEADERS, {"status": AccrualStatus.REVERSED}
            ),
            expected_rows=2,
            total_count=2,
            has_more=False,
        )
        base = find_accrual(reversed_rows, FeeType.BASE, FeeVariant.PROVISIONAL)
        incentive = find_accrual(reversed_rows, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)
        assert base["amount_cents"] == 780000
        assert incentive["amount_cents"] == 1922000

        assert_page(
            scenario.api.list_distributions(state["package_id"], MANAGER_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], MANAGER_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_the_disputed_dimension_dominates_the_roll_up(self, scenario):
        """PRD §3.6: "The `package_status` is recomputed, and because a disputed financial
        dimension dominates the roll-up, the package reads `CONTESTED`."

        Design: Corner/state_machines/financial_dispute_reverses_accruals_and_creates_no_distribution
        """
        state = _dispute_branch_hotel(scenario)

        disputed = scenario.review_package(
            state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.DISPUTE
        )

        assert disputed["financial_status"] == FinancialStatus.DISPUTED
        assert disputed["package_status"] == PackageStatus.CONTESTED

    def test_the_resubmission_counts_the_round_and_raises_a_fresh_set(self, scenario):
        """PRD §3.4: "The `DISPUTED` origin additionally increments `resubmission_count` by one;
        the `PENDING` origin leaves it at zero." And "A resubmission after a dispute recomputes
        the fee amounts and creates a whole fresh accrual set rather than editing the old one."

        Design: Corner/state_machines/financial_dispute_reverses_accruals_and_creates_no_distribution
        """
        state = _dispute_branch_hotel(scenario)
        scenario.review_package(
            state["package_id"], ReviewDimension.FINANCIAL, ReviewDecision.DISPUTE
        )

        resubmitted = scenario.submit_package(state["package_id"])

        assert resubmitted["financial_status"] == FinancialStatus.SUBMITTED
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["agop_cents"] == 20220000
        # The two reversed rows stay for audit beside the fresh ACCRUED pair.
        assert_page(
            scenario.api.list_fee_accruals(state["package_id"], ASSET_HEADERS),
            expected_rows=4,
            total_count=4,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# REQUESTED -> WAIVED_OFFSET: the call the waterfall extinguishes
# ---------------------------------------------------------------------------


def _waived_offset_hotel(scenario):
    """A manual floor-restoration call that bucket one is about to make redundant."""
    agreement = scenario.register(
        hotel_name="Waived Offset Hotel",
        owner_entity_name="Offset Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        working_capital_floor_cents=500000,
        initial_working_capital_cents=0,
        funding_due_days=15,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    call = scenario.call(
        agreement["id"], amount_cents=500000, reason=CallReason.FLOOR_RESTORATION
    )
    package = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=9,
        closing_cash_available_cents=500000,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    distribution = scenario.only_distribution(package["id"])

    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "call_id": call["id"],
        "distribution_id": distribution["id"],
    }


class TestDistributionExecutionWaivesTheOffsettingCall:
    def test_bucket_one_consumes_the_whole_snapshot(self, scenario):
        """PRD §3.6: "Cash is then allocated in a fixed order, each bucket taking the smaller of
        the cash still unallocated and its own demand, and each allocation reducing what remains
        for the next." And "Finally `shortfall_cents` records the aggregate unmet demand: the sum
        of the five demands, less the sum of the five amounts actually allocated."

        Design: Corner/state_machines/distribution_execution_waives_offsetting_floor_restoration_call
        """
        state = _waived_offset_hotel(scenario)

        executed = assert_object_envelope(
            scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS), 200
        )

        assert executed["status"] == DistributionStatus.EXECUTED
        assert executed["available_cash_cents"] == 500000
        assert executed["wc_restoration_cents"] == 500000
        assert executed["base_fee_paid_cents"] == 0
        assert executed["reserve_contribution_cents"] == 0
        assert executed["owner_priority_paid_cents"] == 0
        assert executed["incentive_fee_paid_cents"] == 0
        assert executed["residual_to_owner_cents"] == 0
        # 500000 + 780000 + 1040000 + 1000000 + 1922000 demanded, 500000 allocated.
        assert executed["shortfall_cents"] == 4742000

    def test_the_restoration_extinguishes_the_manual_call_without_funding_it(self, scenario):
        """PRD §3.6: "Every working capital call of that agreement whose `reason` is
        `FLOOR_RESTORATION` and whose `status` is `REQUESTED` moves `REQUESTED → WAIVED_OFFSET`
        when that restoration amount alone lifts `working_capital_balance_cents` to or above the
        agreement's `working_capital_floor_cents`, processed in `created_at` ascending order, with
        `funded_amount_cents` left at zero — the call is extinguished by the offsetting
        distribution rather than funded." And "a manually raised call carries `auto_created`
        false, while every cascade-raised call carries `auto_created` true."

        Design: Corner/state_machines/distribution_execution_waives_offsetting_floor_restoration_call
        """
        state = _waived_offset_hotel(scenario)

        scenario.execute_distribution(state["distribution_id"])

        assert (
            scenario.read_agreement(state["agreement_id"])["working_capital_balance_cents"]
            == 500000
        )
        rows = assert_page(
            scenario.api.list_working_capital_calls(
                state["agreement_id"],
                ASSET_HEADERS,
                {"reason": CallReason.FLOOR_RESTORATION},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["id"] == state["call_id"]
        assert rows[0]["status"] == CallStatus.WAIVED_OFFSET
        assert rows[0]["funded_amount_cents"] == 0
        assert rows[0]["auto_created"] is False

    def test_the_shortfall_call_and_the_empty_reserve_are_untouched(self, scenario):
        """PRD §3.6: "a call with `reason` `DISTRIBUTION_SHORTFALL`, `amount_cents` equal to the
        distribution's `shortfall_cents`, `auto_created` set to true and `status` `REQUESTED`."
        And "a reserve ledger entry is appended with `entry_type` `CONTRIBUTION`, `amount_cents`
        equal to `reserve_contribution_cents` and `source_kind` `DISTRIBUTION_EXECUTION`, with
        the agreement's `ffe_reserve_balance_cents` increased by the same amount; that append is
        skipped when `reserve_contribution_cents` is zero."

        Design: Corner/state_machines/distribution_execution_waives_offsetting_floor_restoration_call
        """
        state = _waived_offset_hotel(scenario)

        scenario.execute_distribution(state["distribution_id"])

        shortfall_calls = assert_page(
            scenario.api.list_working_capital_calls(
                state["agreement_id"],
                ASSET_HEADERS,
                {"reason": CallReason.DISTRIBUTION_SHORTFALL},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert shortfall_calls[0]["amount_cents"] == 4742000
        assert shortfall_calls[0]["status"] == CallStatus.REQUESTED
        assert shortfall_calls[0]["auto_created"] is True

        assert_page(
            scenario.api.list_reserve_ledger(state["agreement_id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 0


# ---------------------------------------------------------------------------
# ACTIVE -> TERMINATION_NOTICED: the branch that raises the hold
# ---------------------------------------------------------------------------


def _notice_cascade_hotel(scenario):
    """A TERMINATION_TRIGGERED test over an agreement still ACTIVE, with cash and a pending ask."""
    agreement = scenario.register(
        hotel_name="Notice Cascade Hotel",
        owner_entity_name="Cascade Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
        min_benchmark_months=1,
        test_periods_expected=1,
        consecutive_failure_limit=1,
        termination_notice_days=90,
    )
    scenario.activate(agreement["id"])
    budget_2026 = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget_2026["id"])
    scenario.decide_budget(budget_2026["id"], BudgetDecision.APPROVE)
    budget_2027 = scenario.budget(
        agreement["id"],
        fiscal_year=2027,
        budgeted_revenue_cents=310000000,
        budgeted_operating_expenses_cents=205000000,
    )
    scenario.submit_budget(budget_2027["id"])
    variance = scenario.variance(
        budget_2026["id"],
        category=VarianceCategory.OPERATING,
        requested_amount_cents=60000000,
        justification="hurricane restoration programme",
    )
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.benchmark(package["id"])
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    test = scenario.performance_test(agreement["id"], 2026)
    return {
        "agreement_id": agreement["id"],
        "budget_2026_id": budget_2026["id"],
        "budget_2027_id": budget_2027["id"],
        "variance_id": variance["id"],
        "package_id": package["id"],
        "test_id": test["id"],
        "test": test,
    }


class TestTerminationNoticeFromActive:
    def test_the_notice_raises_the_hold_and_dates_the_termination(self, scenario):
        """PRD §3.7: "If the new streak has reached or passed the limit, the test lands in
        `TERMINATION_TRIGGERED`: the agreement's `performance_failure_streak` is incremented by one,
        `cure_deadline_utc` stays null because no cure right arises at all, and the agreement's
        `status` stays `ACTIVE` until the owner chooses to issue notice." And "From
        `ACTIVE → TERMINATION_NOTICED`: `termination_effective_utc` is set the same way;
        `distribution_hold` is set to true, which was not previously the case"

        Design: Corner/state_machines/termination_notice_from_active_denies_pending_variance_and_holds_distributions
        """
        state = _notice_cascade_hotel(scenario)
        assert state["test"]["status"] == TestStatus.TERMINATION_TRIGGERED
        assert state["test"]["cure_deadline_utc"] is None
        assert scenario.read_agreement(state["agreement_id"])["status"] == AgreementStatus.ACTIVE

        noticed = scenario.terminate_test(state["test_id"])

        assert noticed["status"] == TestStatus.TERMINATED_NOTICE_ISSUED
        assert noticed["streak_after_test"] == 1
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.TERMINATION_NOTICED
        assert agreement["distribution_hold"] is True
        assert agreement["termination_effective_utc"].startswith("2026-10-30T00:00:00")

    def test_the_notice_denies_the_pending_ask_and_freezes_the_cash_but_spares_the_budgets(
        self, scenario
    ):
        """PRD §3.7: "every `CALCULATED` distribution of the agreement moves to `HELD` in
        `created_at` ascending order; and every `PENDING` variance request moves to `DENIED` with
        `denied_by_cascade` true in `created_at` ascending order. The asymmetry is deliberate — the
        `ACTIVE` branch must raise the hold and freeze distributions that the `CURE_PERIOD` branch
        had already frozen, while the `CURE_PERIOD` branch additionally sweeps away submitted
        budgets."

        Design: Corner/state_machines/termination_notice_from_active_denies_pending_variance_and_holds_distributions
        """
        state = _notice_cascade_hotel(scenario)

        scenario.terminate_test(state["test_id"])

        denied = scenario.variances(state["budget_2026_id"])[0]
        assert denied["id"] == state["variance_id"]
        assert denied["status"] == VarianceStatus.DENIED
        assert denied["denied_by_cascade"] is True
        assert denied["decided_by_user_id"] is None
        assert denied["approval_level"] == ApprovalLevel.OWNER_REP
        # Only the CURE_PERIOD branch supersedes submitted budgets.
        assert scenario.read_budget(state["budget_2027_id"])["status"] == BudgetStatus.SUBMITTED
        approved = scenario.read_budget(state["budget_2026_id"])
        assert approved["status"] == BudgetStatus.APPROVED
        assert approved["carryforward_applied"] is False
        held = assert_page(
            scenario.api.list_distributions(
                state["package_id"], ASSET_HEADERS, {"status": DistributionStatus.HELD}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert held[0]["shortfall_cents"] == 3702000
