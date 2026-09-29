"""Guard rules refusing a bad body, and the neighbouring body that is admitted."""

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    AccrualStatus,
    AgreementStatus,
    AllocationBasis,
    ApiErrorId,
    ApprovalLevel,
    BenchmarkSource,
    BudgetDecision,
    BudgetSourceStatus,
    BudgetStatus,
    CallReason,
    CallStatus,
    DEFAULT_LIMIT,
    DisclosureStatus,
    DisputeStatus,
    DistributionStatus,
    FeeType,
    FeeVariant,
    FundingSource,
    MANAGER_HEADERS,
    OWNER_HEADERS,
    OWNER_USER_ID,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    TestStatus,
    adjust_payload,
    VarianceCategory,
    VarianceStatus,
    assert_array_envelope,
    assert_error_envelope,
    assert_gop_achievement,
    assert_object_envelope,
    assert_page,
    assert_rpi,
    assert_variance_pct,
    budget_decision_payload,
    charge_payload,
    find_accrual,
    fund_payload,
    performance_test_payload,
    pay_cure_payload,
    resolve_owner_funds_payload,
    variance_payload,
)


# ---------------------------------------------------------------------------
# A deferral the owner cannot audit
# ---------------------------------------------------------------------------


def _chargeback_detail_hotel(scenario):
    """One open period of 26000000 gross revenue under a 0.015 cap."""
    agreement = scenario.register(
        hotel_name="Chargeback Detail Hotel",
        owner_entity_name="Detail Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        centralized_services_cap_pct=0.015,
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
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


def _deferral_body(**overrides):
    return charge_payload(
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=6000000,
        hotel_basis_share=0.05,
        allow_deferral=True,
        **overrides,
    )


class TestChargebackDeferralRequiresSupportingDetail:
    def test_a_deferral_without_supporting_detail_persists_nothing(self, scenario):
        """PRD §2.8 rule 39: "A charge posted with `allow_deferral` true also carries
        `supporting_detail_provided` true; otherwise `ERR_CHARGEBACK_DETAIL_REQUIRED` (422)." PRD
        §3.4: "And a charge posted with `allow_deferral` true but `supporting_detail_provided`
        false is refused with `ERR_CHARGEBACK_DETAIL_REQUIRED`"

        Design: Corner/validations/chargeback_with_deferral_but_no_supporting_detail_rejected
        """
        state = _chargeback_detail_hotel(scenario)

        response = scenario.api.create_centralized_charge(
            state["package_id"], _deferral_body(supporting_detail_provided=False), MANAGER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.CHARGEBACK_DETAIL_REQUIRED)
        assert response.status_code == 422
        assert_page(
            scenario.api.list_centralized_charges(state["package_id"], OWNER_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        assert scenario.read_package(state["package_id"])["allocated_centralized_cents"] == 0

    def test_the_identical_body_with_the_detail_flag_is_admitted(self, scenario):
        """PRD §3.4: "The period cap is the package's `gross_revenue_cents` multiplied by the
        agreement's `centralized_services_cap_pct` and floored to whole cents." And "Each charge's
        `requested_amount_cents` is its `pool_amount_cents` multiplied by its `hotel_basis_share`,
        rounded half up to whole cents." And "Finally the package's `allocated_centralized_cents`
        is set to the sum of the allocated amounts across all its charges." And "Every charge
        starts life with `disclosure_status` `DISCLOSED` and `adjusted_amount_cents` null."

        Design: Corner/validations/chargeback_with_deferral_but_no_supporting_detail_rejected
        """
        state = _chargeback_detail_hotel(scenario)

        created = assert_object_envelope(
            scenario.api.create_centralized_charge(
                state["package_id"],
                _deferral_body(supporting_detail_provided=True),
                MANAGER_HEADERS,
            ),
            201,
        )

        # 300000 requested sits well inside the 390000 period cap.
        assert created["requested_amount_cents"] == 300000
        assert created["allocated_amount_cents"] == 300000
        assert created["deferred_amount_cents"] == 0
        assert created["disclosure_status"] == DisclosureStatus.DISCLOSED
        assert created["adjusted_amount_cents"] is None
        assert_page(
            scenario.api.list_centralized_charges(state["package_id"], OWNER_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert scenario.read_package(state["package_id"])["allocated_centralized_cents"] == 300000


# ---------------------------------------------------------------------------
# Funding is all-or-nothing to the cent
# ---------------------------------------------------------------------------


def _exact_funding_hotel(scenario):
    """One manually raised 500000 floor-restoration call against an empty account."""
    agreement = scenario.register(
        hotel_name="Exact Funding Hotel",
        owner_entity_name="Funding Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        initial_working_capital_cents=0,
        working_capital_floor_cents=0,
        funding_due_days=15,
    )
    scenario.activate(agreement["id"])
    call = scenario.call(
        agreement["id"], amount_cents=500000, reason=CallReason.FLOOR_RESTORATION
    )
    return {"agreement_id": agreement["id"], "call_id": call["id"]}


class TestWorkingCapitalFundingMustMatchExactly:
    def test_one_cent_under_and_one_cent_over_are_both_refused(self, scenario):
        """PRD §3.6: "Partial funding is not a concept here: the amount must equal the call's
        `amount_cents` exactly, and anything else is refused with `ERR_FUNDING_AMOUNT_MISMATCH`."
        PRD §2.9: "`working_capital_balance_cents` is seeded from `initial_working_capital_cents`
        at activation and thereafter moves only through funded calls, the first bucket of an
        executed distribution, a paid cure and employment-claim allocations"

        Design: Corner/validations/working_capital_funding_must_match_the_call_amount_exactly
        """
        state = _exact_funding_hotel(scenario)

        low = scenario.api.fund_working_capital_call(
            state["call_id"], fund_payload(499999), OWNER_HEADERS
        )
        high = scenario.api.fund_working_capital_call(
            state["call_id"], fund_payload(500001), OWNER_HEADERS
        )

        assert_error_envelope(low, ApiErrorId.FUNDING_AMOUNT_MISMATCH)
        assert low.status_code == 422
        assert_error_envelope(high, ApiErrorId.FUNDING_AMOUNT_MISMATCH)
        assert high.status_code == 422
        assert scenario.only_call(state["agreement_id"])["status"] == CallStatus.REQUESTED
        assert scenario.read_agreement(state["agreement_id"])["working_capital_balance_cents"] == 0

    def test_the_exact_amount_credits_the_balance_once(self, scenario):
        """PRD §3.6: "A call may be funded from `REQUESTED → FUNDED`, which records the funded
        amount and increases the agreement's `working_capital_balance_cents` by the call's
        `amount_cents`" And "a manually raised call carries `auto_created` false, while every
        cascade-raised call carries `auto_created` true. Every call, however raised, has its
        `due_date_utc` set to the logical clock at the moment of issue advanced by the agreement's
        `funding_due_days`."

        Design: Corner/validations/working_capital_funding_must_match_the_call_amount_exactly
        """
        state = _exact_funding_hotel(scenario)
        scenario.api.fund_working_capital_call(
            state["call_id"], fund_payload(499999), OWNER_HEADERS
        )

        funded = assert_object_envelope(
            scenario.api.fund_working_capital_call(
                state["call_id"], fund_payload(500000), OWNER_HEADERS
            ),
            200,
        )

        assert funded["status"] == CallStatus.FUNDED
        assert funded["funded_amount_cents"] == 500000
        assert funded["auto_created"] is False
        assert funded["due_date_utc"].startswith("2026-08-16T00:00:00")
        # The refused attempt moved nothing, so the credit lands exactly once.
        assert (
            scenario.read_agreement(state["agreement_id"])["working_capital_balance_cents"]
            == 500000
        )


# ---------------------------------------------------------------------------
# The inclusive ceiling on an adjustment
# ---------------------------------------------------------------------------


def _adjust_range_hotel(scenario):
    """A submitted period whose 300000 reservations charge has been contested."""
    agreement = scenario.register(
        hotel_name="Adjust Range Hotel",
        owner_entity_name="Adjust Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        centralized_services_cap_pct=0.015,
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
    charge = scenario.charge(
        package["id"],
        service_code=ServiceCode.RESERVATIONS,
        allocation_basis=AllocationBasis.GROSS_REVENUE,
        pool_amount_cents=6000000,
        hotel_basis_share=0.05,
    )
    scenario.submit_package(package["id"])
    scenario.contest_charge(charge["id"])
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "charge_id": charge["id"],
    }


class TestChargeAdjustmentRange:
    def test_one_cent_above_the_allocated_amount_is_refused(self, scenario):
        """PRD §2.8 rule 48: "`adjusted_amount_cents` is present and between 0 and the charge's
        `allocated_amount_cents` inclusive; otherwise `ERR_ADJUSTMENT_OUT_OF_RANGE` (422)." PRD
        §3.5: "the value must be present and between 0 and the charge's current
        `allocated_amount_cents` inclusive, or the request is refused with
        `ERR_ADJUSTMENT_OUT_OF_RANGE`."

        Design: Corner/validations/charge_adjustment_above_the_allocated_amount_rejected
        """
        state = _adjust_range_hotel(scenario)

        response = scenario.api.review_centralized_charge(
            state["charge_id"], adjust_payload(300001), MANAGER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.ADJUSTMENT_OUT_OF_RANGE)
        assert response.status_code == 422
        charge = scenario.charges(state["package_id"])[0]
        assert charge["disclosure_status"] == DisclosureStatus.CONTESTED
        assert charge["allocated_amount_cents"] == 300000
        # PRD §3.5: the contest parked the centralized accrual and froze the period's cash.
        held = find_accrual(
            scenario.accruals(state["package_id"]),
            FeeType.CENTRALIZED_SERVICES,
            FeeVariant.PROVISIONAL,
        )
        assert held["status"] == AccrualStatus.DISPUTED_HELD
        package = scenario.read_package(state["package_id"])
        assert package["agop_cents"] == 19920000
        assert package["incentive_fee_provisional_cents"] == 1892000

    def test_an_adjustment_inside_the_range_cascades_into_profit_and_accruals(self, scenario):
        """PRD §3.5: "First, the charge's `allocated_amount_cents` is replaced by
        `adjusted_amount_cents` and its `deferred_amount_cents` is recomputed as its
        `requested_amount_cents` less the new allocated amount. Second, because the charge's
        allocated amount changed, the package's `allocated_centralized_cents`, its `agop_cents` and
        its `incentive_fee_provisional_cents` are all recomputed by the same pinned five-step order
        described in §3.4" And "the package's `INCENTIVE` accrual of `variant` `PROVISIONAL` has
        its `amount_cents` rewritten to the new value, and the `CENTRALIZED_SERVICES` accrual has
        its `amount_cents` rewritten to the adjusted amount and is returned from `DISPUTED_HELD` to
        whichever status it held before the contest"

        Design: Corner/validations/charge_adjustment_above_the_allocated_amount_rejected
        """
        state = _adjust_range_hotel(scenario)

        adjusted = assert_object_envelope(
            scenario.api.review_centralized_charge(
                state["charge_id"],
                adjust_payload(250000),
                MANAGER_HEADERS,
            ),
            200,
        )

        assert adjusted["disclosure_status"] == DisclosureStatus.ADJUSTED
        assert adjusted["allocated_amount_cents"] == 250000
        assert adjusted["deferred_amount_cents"] == 50000
        package = scenario.read_package(state["package_id"])
        assert package["allocated_centralized_cents"] == 250000
        # A 50000 smaller chargeback lifts the profit and therefore the provisional fee.
        assert package["agop_cents"] == 19970000
        assert package["incentive_fee_provisional_cents"] == 1897000
        accruals = scenario.accruals(state["package_id"])
        centralized = find_accrual(
            accruals, FeeType.CENTRALIZED_SERVICES, FeeVariant.PROVISIONAL
        )
        assert centralized["status"] == AccrualStatus.ACCRUED
        assert centralized["amount_cents"] == 250000
        assert (
            find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)["amount_cents"]
            == 1897000
        )


# ---------------------------------------------------------------------------
# A reserve too thin to fund the disputed remediation
# ---------------------------------------------------------------------------


def _reserve_guard_hotel(scenario):
    """A dispute restated to 500000 against a reserve that has never been funded."""
    agreement = scenario.register(
        hotel_name="Reserve Guard Hotel",
        owner_entity_name="Reserve Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        funding_due_days=15,
        max_dispute_rounds=2,
        dispute_standstill_days=45,
    )
    scenario.activate(agreement["id"])
    dispute = scenario.dispute(
        agreement["id"],
        franchise_requirement_ref="BRAND-STD-LOBBY-2026",
        estimated_cost_cents=400000,
        remediation_start_utc="2026-09-01T00:00:00Z",
        remediation_deadline_utc="2026-12-01T00:00:00Z",
    )
    scenario.manager_response(dispute["id"], 500000)
    return {"agreement_id": agreement["id"], "dispute_id": dispute["id"]}


class TestReserveFundedResolutionNeedsTheBalance:
    def test_an_empty_reserve_refuses_the_reserve_funding_source(self, scenario):
        """PRD §3.9: "Under `FFE_RESERVE` the agreement's `ffe_reserve_balance_cents` must be at
        least `current_cost_estimate_cents`, and a thinner reserve is refused with
        `ERR_INSUFFICIENT_RESERVE_BALANCE`"

        Design: Corner/validations/reserve_funded_dispute_resolution_beyond_the_balance_rejected
        """
        state = _reserve_guard_hotel(scenario)

        response = scenario.api.advance_brand_dispute(
            state["dispute_id"],
            resolve_owner_funds_payload(FundingSource.FFE_RESERVE),
            OWNER_HEADERS,
        )

        assert_error_envelope(response, ApiErrorId.INSUFFICIENT_RESERVE_BALANCE)
        assert response.status_code == 422
        dispute = scenario.disputes(state["agreement_id"])[0]
        assert dispute["status"] == DisputeStatus.MANAGER_RESPONDED
        assert dispute["current_cost_estimate_cents"] == 500000
        assert_page(
            scenario.api.list_reserve_ledger(state["agreement_id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_the_owner_contribution_route_raises_a_call_and_leaves_the_ledger_empty(
        self, scenario
    ):
        """PRD §3.9: "Under `OWNER_CONTRIBUTION` the reserve is untouched — there is no balance
        requirement at all and no ledger entry — and instead a working capital call is created
        with `reason` `FLOOR_RESTORATION`, `amount_cents` equal to `current_cost_estimate_cents`,
        `auto_created` true and `status` `REQUESTED`, which the owner then funds through the
        ordinary funding route." And "requires a `funding_source` and sets `funded_amount_cents` to
        `current_cost_estimate_cents` — the figure standing at the moment of resolution, whichever
        party last moved it."

        Design: Corner/validations/reserve_funded_dispute_resolution_beyond_the_balance_rejected
        """
        state = _reserve_guard_hotel(scenario)
        scenario.api.advance_brand_dispute(
            state["dispute_id"],
            resolve_owner_funds_payload(FundingSource.FFE_RESERVE),
            OWNER_HEADERS,
        )

        resolved = assert_object_envelope(
            scenario.api.advance_brand_dispute(
                state["dispute_id"],
                resolve_owner_funds_payload(FundingSource.OWNER_CONTRIBUTION),
                OWNER_HEADERS,
            ),
            200,
        )

        assert resolved["status"] == DisputeStatus.RESOLVED_OWNER_FUNDS
        assert resolved["funded_amount_cents"] == 500000
        assert resolved["funding_source"] == FundingSource.OWNER_CONTRIBUTION
        # Only the owner's counter counts a round, and none was posted.
        assert resolved["round"] == 0
        rows = assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], ASSET_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["reason"] == CallReason.FLOOR_RESTORATION
        assert rows[0]["amount_cents"] == 500000
        assert rows[0]["auto_created"] is True
        assert rows[0]["status"] == CallStatus.REQUESTED
        assert rows[0]["due_date_utc"].startswith("2026-08-16T00:00:00")
        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 0
        assert_page(
            scenario.api.list_reserve_ledger(state["agreement_id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# The cure payment floor and the inclusive cure window
# ---------------------------------------------------------------------------


def _curable_failure_hotel(scenario, hotel_name, owner_name):
    """A FAILED_CURABLE test owing 66280000, with the period's cash frozen."""
    agreement = scenario.register(
        hotel_name=hotel_name,
        owner_entity_name=owner_name,
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
        consecutive_failure_limit=2,
        cure_window_days=60,
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

    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.benchmark(package["id"])
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    test = scenario.performance_test(agreement["id"], 2026)
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "test_id": test["id"],
        "test": test,
    }


class TestCurePaymentMustCoverTheShortfall:
    def test_one_cent_short_of_the_amount_due_is_refused(self, scenario):
        """PRD §3.7: "`cure_payment_due_cents` is the pro-rated budgeted profit less the actual
        profit, floored at zero." And "A `PAY_CURE` action moves the test `CURE_ELECTED → CURED`
        and requires `payment_amount_cents` to be at least `cure_payment_due_cents`, refusing
        anything smaller with `ERR_CURE_PAYMENT_INSUFFICIENT`."

        Design: Corner/validations/cure_payment_one_cent_short_rejected_then_exact_payment_accepted
        """
        state = _curable_failure_hotel(scenario, "Cure Payment Hotel", "Cure Owner LLC")
        assert state["test"]["status"] == TestStatus.FAILED_CURABLE
        assert state["test"]["cure_payment_due_cents"] == 66280000
        assert state["test"]["cure_deadline_utc"].startswith("2026-09-30T00:00:00")
        assert state["test"]["streak_after_test"] == 1
        scenario.elect_cure(state["test_id"])

        response = scenario.api.cure_performance_test(
            state["test_id"], pay_cure_payload(66279999), MANAGER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.CURE_PAYMENT_INSUFFICIENT)
        assert response.status_code == 422
        assert scenario.performance_tests(state["agreement_id"])[0]["status"] == (
            TestStatus.CURE_ELECTED
        )
        assert scenario.read_agreement(state["agreement_id"])["status"] == (
            AgreementStatus.CURE_PERIOD
        )

    def test_the_exact_amount_cures_the_failure_and_credits_the_account(self, scenario):
        """PRD §3.7: "A sufficient payment writes `cure_paid_cents` as the amount paid and returns
        the agreement `CURE_PERIOD → ACTIVE`, which resets `performance_failure_streak` to 0,
        increases `working_capital_balance_cents` by the amount actually paid, sets
        `distribution_hold` to false"

        Design: Corner/validations/cure_payment_one_cent_short_rejected_then_exact_payment_accepted
        """
        state = _curable_failure_hotel(scenario, "Cure Payment Hotel", "Cure Owner LLC")
        scenario.elect_cure(state["test_id"])
        scenario.api.cure_performance_test(
            state["test_id"], pay_cure_payload(66279999), MANAGER_HEADERS
        )

        cured = assert_object_envelope(
            scenario.api.cure_performance_test(
                state["test_id"], pay_cure_payload(66280000), MANAGER_HEADERS
            ),
            200,
        )

        assert cured["status"] == TestStatus.CURED
        assert cured["cure_paid_cents"] == 66280000
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["performance_failure_streak"] == 0
        assert agreement["distribution_hold"] is False
        assert agreement["working_capital_balance_cents"] == 66280000

    def test_the_released_distribution_keeps_the_buckets_it_was_computed_with(self, scenario):
        """PRD §3.7: "and — because the hold came down — returns every `HELD` distribution of the
        agreement to `CALCULATED` in `created_at` ascending order with bucket amounts untouched."
        PRD §3.6: "Distribution lists are filterable by `status`."

        Design: Corner/validations/cure_payment_one_cent_short_rejected_then_exact_payment_accepted
        """
        state = _curable_failure_hotel(scenario, "Cure Payment Hotel", "Cure Owner LLC")
        scenario.elect_cure(state["test_id"])
        scenario.pay_cure(state["test_id"], 66280000)

        rows = assert_page(
            scenario.api.list_distributions(
                state["package_id"], MANAGER_HEADERS, {"status": DistributionStatus.CALCULATED}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )

        # 780000 + 1000000 + 1922000 of demand against an empty operating account.
        assert rows[0]["available_cash_cents"] == 0
        assert rows[0]["base_fee_paid_cents"] == 0
        assert rows[0]["reserve_contribution_cents"] == 0
        assert rows[0]["owner_priority_paid_cents"] == 0
        assert rows[0]["incentive_fee_paid_cents"] == 0
        assert rows[0]["residual_to_owner_cents"] == 0
        assert rows[0]["shortfall_cents"] == 3702000


class TestCureAtExactlyTheDeadline:
    def test_the_lapse_sweep_is_strict_while_the_overdue_sweep_has_already_fired(self, scenario):
        """PRD §2.10: "Every performance test in `FAILED_CURABLE` or `CURE_ELECTED` whose
        `cure_deadline_utc` is strictly before the new clock value becomes `TERMINATION_TRIGGERED`.
        The count is reported as `lapsed_cure_count`." And "Every working capital call in
        `REQUESTED` whose `due_date_utc` is strictly before the new clock value becomes `OVERDUE`,
        with no cash movement. The count is reported as `overdue_call_count`." And "Steps 1 through
        3 fire only once the clock has passed the deadline; steps 4 and 5 fire when the clock
        reaches it."

        Design: Corner/validations/cure_elected_and_paid_at_exactly_the_deadline_is_accepted
        """
        state = _curable_failure_hotel(scenario, "Cure Deadline Hotel", "Deadline Owner LLC")

        sweep = scenario.set_clock("2026-09-30T00:00:00Z")

        assert sweep["current_utc"].startswith("2026-09-30T00:00:00")
        assert sweep["lapsed_cure_count"] == 0
        assert sweep["overdue_call_count"] == 1
        # Standing exactly on the deadline, the cure right is still alive.
        assert scenario.performance_tests(state["agreement_id"])[0]["status"] == (
            TestStatus.FAILED_CURABLE
        )

    def test_both_cure_steps_still_succeed_at_the_deadline_instant(self, scenario):
        """PRD §2.8 rule 34: "The logical clock is at or before `cure_deadline_utc`; otherwise
        `ERR_CURE_WINDOW_CLOSED` (409)." PRD §3.7: "An `ELECT_CURE` action moves the test
        `FAILED_CURABLE → CURE_ELECTED` and moves no cash — it merely records that the manager
        intends to cure."

        Design: Corner/validations/cure_elected_and_paid_at_exactly_the_deadline_is_accepted
        """
        state = _curable_failure_hotel(scenario, "Cure Deadline Hotel", "Deadline Owner LLC")
        scenario.set_clock("2026-09-30T00:00:00Z")

        elected = scenario.elect_cure(state["test_id"])
        cured = scenario.pay_cure(state["test_id"], 66280000)

        assert elected["status"] == TestStatus.CURE_ELECTED
        assert cured["status"] == TestStatus.CURED
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["distribution_hold"] is False
        assert agreement["working_capital_balance_cents"] == 66280000
        # The shortfall call the accepted period raised is past its own due date.
        call = scenario.only_call(state["agreement_id"])
        assert call["status"] == CallStatus.OVERDUE
        assert call["reason"] == CallReason.DISTRIBUTION_SHORTFALL
        assert call["amount_cents"] == 3702000


# ---------------------------------------------------------------------------
# A manager estimate is not benchmark data
# ---------------------------------------------------------------------------


def _benchmark_data_hotel(scenario):
    """One accepted period whose only benchmark came from the manager."""
    agreement = scenario.register(
        hotel_name="Benchmark Data Hotel",
        owner_entity_name="Data Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
        gop_test_threshold_pct=0.85,
        rpi_test_threshold=90.0,
        min_benchmark_months=1,
        test_periods_expected=2,
        consecutive_failure_limit=2,
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
    scenario.benchmark(package["id"], source=BenchmarkSource.MANAGER_ESTIMATE)
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


def _add_str_month(scenario, agreement_id):
    """A second accepted period carrying a qualifying third-party benchmark."""
    package = scenario.package(
        agreement_id,
        fiscal_year=2026,
        period_month=10,
        rooms_revenue_cents=10000000,
        fnb_revenue_cents=0,
        other_revenue_cents=0,
        operating_expenses_cents=3000000,
        closing_cash_available_cents=0,
    )
    scenario.benchmark(
        package["id"],
        hotel_revpar_cents=11000,
        comp_set_revpar_cents=12000,
        rooms_available=3000,
        source=BenchmarkSource.STR_REPORT,
    )
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return package


class TestPerformanceTestNeedsQualifyingBenchmarkMonths:
    def test_a_manager_estimate_month_cannot_score_the_test(self, scenario):
        """PRD §2.8 rule 42: "The count of non-superseded `STR_REPORT` benchmarks sitting on
        accepted periods whose `benchmark_status` is `ACCEPTED` is at least the agreement's
        `min_benchmark_months`; otherwise `ERR_INSUFFICIENT_BENCHMARK_DATA` (422)." PRD §3.7:
        "`MANAGER_ESTIMATE` rows never count, and a challenged month never counts."

        Design: Corner/validations/performance_test_without_str_benchmarks_rejected_then_scores_after_a_qualifying_month
        """
        state = _benchmark_data_hotel(scenario)

        response = scenario.api.create_performance_test(
            state["agreement_id"], performance_test_payload(2026), ADMIN_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.INSUFFICIENT_BENCHMARK_DATA)
        assert response.status_code == 422
        assert_page(
            scenario.api.list_performance_tests(state["agreement_id"], ADMIN_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_one_qualifying_month_lets_the_same_call_score(self, scenario):
        """PRD §3.7: "Their number is recorded as `str_month_count`, and if it falls below the
        agreement's `min_benchmark_months` — ten months out of twelve by default — the test is
        refused with `ERR_INSUFFICIENT_BENCHMARK_DATA`." And "The actual side is
        `actual_agop_cents`, the sum of `agop_cents` over the accepted periods, and
        `gop_achievement_pct` is the actual divided by the pro-rated budget, rounded to four
        decimal places."

        Design: Corner/validations/performance_test_without_str_benchmarks_rejected_then_scores_after_a_qualifying_month
        """
        state = _benchmark_data_hotel(scenario)
        scenario.api.create_performance_test(
            state["agreement_id"], performance_test_payload(2026), ADMIN_HEADERS
        )
        _add_str_month(scenario, state["agreement_id"])

        test = assert_object_envelope(
            scenario.api.create_performance_test(
                state["agreement_id"], performance_test_payload(2026), ADMIN_HEADERS
            ),
            201,
        )

        # Two accepted periods, but only the STR_REPORT month enters the index.
        assert test["str_month_count"] == 1
        assert test["accepted_period_count"] == 2
        assert test["actual_agop_cents"] == 26920000
        assert test["prorated_budget_agop_cents"] == 86500000
        assert_gop_achievement(test["gop_achievement_pct"], 0.3112)
        assert_rpi(test["rpi_weighted"], 91.67)
        assert test["status"] == TestStatus.PASSED
        assert test["budgeted_agop_snapshot_cents"] == 86500000
        assert test["budget_source_status"] == BudgetSourceStatus.APPROVED


# ---------------------------------------------------------------------------
# A capital line nobody budgeted
# ---------------------------------------------------------------------------


def _zero_baseline_hotel(scenario):
    """An approved budget with both capital lines budgeted at zero."""
    agreement = scenario.register(
        hotel_name="Zero Baseline Hotel",
        owner_entity_name="Zero Owner LLC",
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
        budgeted_capital_ffe_cents=0,
        budgeted_capital_brand_cents=0,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestVarianceAgainstAZeroBaseline:
    def test_an_unbudgeted_capital_line_defines_no_ratio(self, scenario):
        """PRD §3.3: "The starting baseline is the budget line matching the category:
        `budgeted_operating_expenses_cents` for `OPERATING`, `budgeted_capital_ffe_cents` for
        `CAPITAL_FFE`, `budgeted_capital_brand_cents` for `CAPITAL_BRAND`." And "If that total is
        not greater than zero — which happens when a capital line was budgeted at zero and nothing
        has been approved against it yet — no ratio is defined and the request is refused with
        `ERR_VARIANCE_BASELINE_ZERO`."

        Design: Corner/validations/variance_against_a_zero_capital_baseline_rejected
        """
        state = _zero_baseline_hotel(scenario)
        assert scenario.read_budget(state["budget_id"])["budgeted_capital_ffe_cents"] == 0

        response = scenario.api.create_variance_request(
            state["budget_id"],
            variance_payload(
                VarianceCategory.CAPITAL_FFE, 500000, justification="unbudgeted soft goods"
            ),
            MANAGER_HEADERS,
        )

        assert_error_envelope(response, ApiErrorId.VARIANCE_BASELINE_ZERO)
        assert response.status_code == 422
        assert_page(
            scenario.api.list_variance_requests(
                state["budget_id"], ASSET_HEADERS, {"category": VarianceCategory.CAPITAL_FFE}
            ),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

    def test_the_same_budgets_operating_line_admits_the_request(self, scenario):
        """PRD §3.3: "Otherwise `variance_pct` is the requested amount divided by the effective
        baseline, rounded to six decimal places." And "A `MANAGER_DISCRETION` request needs no
        decision: it is persisted directly in `status` `AUTO_APPROVED`, `decided_by_user_id` stays
        null, and `PENDING` is never observable for it."

        Design: Corner/validations/variance_against_a_zero_capital_baseline_rejected
        """
        state = _zero_baseline_hotel(scenario)

        created = assert_object_envelope(
            scenario.api.create_variance_request(
                state["budget_id"],
                variance_payload(
                    VarianceCategory.OPERATING, 1000000, justification="utilities overrun"
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert created["effective_baseline_cents"] == 200000000
        assert_variance_pct(created["variance_pct"], 0.005000)
        assert created["approval_level"] == ApprovalLevel.MANAGER_DISCRETION
        assert created["status"] == VarianceStatus.AUTO_APPROVED
        assert created["decided_by_user_id"] is None


# ---------------------------------------------------------------------------
# The one list whose paging arguments are checked
# ---------------------------------------------------------------------------


def _pagination_bounds_hotel(scenario):
    """A single DRAFT budget, so every page has exactly one candidate row."""
    agreement = scenario.register(
        hotel_name="Pagination Bounds Hotel",
        owner_entity_name="Bounds Owner LLC",
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
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestBudgetListPaginationBounds:
    def test_a_limit_above_the_maximum_and_a_negative_offset_are_both_refused(self, scenario):
        """PRD §2.8 rule 5: "`limit` is between 1 and 100 inclusive and `offset` is at least 0;
        otherwise `ERR_INVALID_PAGINATION` (400). Applies to `GET /hotel-management/budgets`."
        PRD §2.3: "`limit` sets the maximum number of rows returned; it defaults to 10, may not be
        below 1 and may not exceed 100. `offset` sets how many rows to skip and defaults to 0; it
        may not be negative."

        Design: Corner/validations/budget_list_pagination_bounds_rejected
        """
        state = _pagination_bounds_hotel(scenario)

        over_limit = scenario.api.list_budgets(
            ASSET_HEADERS, {"agreement_id": state["agreement_id"], "limit": 101}
        )
        under_offset = scenario.api.list_budgets(
            ASSET_HEADERS, {"agreement_id": state["agreement_id"], "offset": -1}
        )

        assert_error_envelope(over_limit, ApiErrorId.INVALID_PAGINATION)
        assert over_limit.status_code == 400
        assert_error_envelope(under_offset, ApiErrorId.INVALID_PAGINATION)
        assert under_offset.status_code == 400

    def test_the_maximum_limit_is_accepted_and_an_absent_limit_falls_back_to_ten(self, scenario):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in
        the `meta` object of the envelope, where `total_count` counts every row matching the
        filters before paging is applied and `has_more` is true whenever rows remain beyond the
        current window."

        Design: Corner/validations/budget_list_pagination_bounds_rejected
        """
        state = _pagination_bounds_hotel(scenario)

        rows, meta = assert_array_envelope(
            scenario.api.list_budgets(
                ASSET_HEADERS, {"agreement_id": state["agreement_id"], "limit": 100}
            )
        )

        assert len(rows) == 1
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        _, defaulted = assert_array_envelope(
            scenario.api.list_budgets(ASSET_HEADERS, {"agreement_id": state["agreement_id"]})
        )
        assert defaulted["limit"] == DEFAULT_LIMIT
        assert defaulted["offset"] == 0


# ---------------------------------------------------------------------------
# Which refusal a late owner decision earns
# ---------------------------------------------------------------------------


def _two_submitted_budgets(scenario):
    """Two agreements whose budgets were both submitted at the epoch."""
    state = {}
    for key, hotel, owner, revenue, opex in (
        ("a", "Window A Hotel", "Window Owner A LLC", 300000000, 200000000),
        ("b", "Window B Hotel", "Window Owner B LLC", 310000000, 205000000),
    ):
        agreement = scenario.register(
            hotel_name=hotel,
            owner_entity_name=owner,
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
            owner_review_window_days=30,
        )
        scenario.activate(agreement["id"])
        budget = scenario.budget(
            agreement["id"],
            fiscal_year=2026,
            budgeted_revenue_cents=revenue,
            budgeted_operating_expenses_cents=opex,
        )
        scenario.submit_budget(budget["id"])
        state[key] = budget["id"]
    return state


class TestDeemedApprovalOutranksTheClosedWindow:
    def test_a_decision_standing_exactly_on_the_deadline_still_succeeds(self, scenario):
        """PRD §3.2: "set `owner_decision_deadline_utc` to `submitted_at` advanced by the
        agreement's `owner_review_window_days`" PRD §2.10: "Every budget in `SUBMITTED` whose
        `owner_decision_deadline_utc` is strictly before the new clock value becomes
        `DEEMED_APPROVED`. The count is reported as `deemed_approved_budget_count`." PRD §2.8 rule
        33: "The logical clock is at or before `owner_decision_deadline_utc`; otherwise
        `ERR_OWNER_DECISION_WINDOW_CLOSED` (409)."

        Design: Corner/validations/deemed_approval_sweep_outranks_the_owner_decision_window_error
        """
        state = _two_submitted_budgets(scenario)
        assert scenario.read_budget(state["a"])["owner_decision_deadline_utc"].startswith(
            "2026-08-31T00:00:00"
        )

        sweep = scenario.set_clock("2026-08-31T00:00:00Z")
        decided = assert_object_envelope(
            scenario.api.decide_budget(
                state["a"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
            ),
            200,
        )

        assert sweep["deemed_approved_budget_count"] == 0
        assert decided["status"] == BudgetStatus.APPROVED
        assert decided["decided_by_user_id"] == OWNER_USER_ID

    def test_once_the_sweep_has_run_the_state_error_wins_over_the_window_error(self, scenario):
        """PRD §2.8: "When a request violates several rules at once, exactly one error is reported:
        the one belonging to the lowest-numbered rule below. The ordering is absolute and spans
        every endpoint." PRD §3.2: "When the logical clock advances strictly past
        `owner_decision_deadline_utc`, the sweep described in §2.10 moves the row
        `SUBMITTED → DEEMED_APPROVED`, and `decided_by_user_id` deliberately stays null: a deemed
        approval is attributed to nobody."

        Design: Corner/validations/deemed_approval_sweep_outranks_the_owner_decision_window_error
        """
        state = _two_submitted_budgets(scenario)
        scenario.set_clock("2026-08-31T00:00:00Z")
        scenario.decide_budget(state["a"], BudgetDecision.APPROVE)

        sweep = scenario.set_clock("2026-09-01T00:00:00Z")
        response = scenario.api.decide_budget(
            state["b"], budget_decision_payload(BudgetDecision.APPROVE), OWNER_HEADERS
        )

        # Only the undecided budget was swept.
        assert sweep["deemed_approved_budget_count"] == 1
        swept = scenario.read_budget(state["b"])
        assert swept["status"] == BudgetStatus.DEEMED_APPROVED
        assert swept["decided_by_user_id"] is None
        # Rule 20 is reached before rule 33, so the state error is the one reported.
        assert_error_envelope(response, ApiErrorId.INVALID_BUDGET_STATE)
        assert response.status_code == 409
        assert scenario.read_budget(state["b"])["decided_by_user_id"] is None
