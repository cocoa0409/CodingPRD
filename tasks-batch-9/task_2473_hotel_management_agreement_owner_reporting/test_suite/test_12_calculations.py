"""Derived figures: rounding direction, input-set filtering and bucket order."""

from test_helpers import (
    ASSET_HEADERS,
    AccrualStatus,
    AgreementStatus,
    ApprovalLevel,
    BudgetDecision,
    BudgetStatus,
    CallReason,
    CallStatus,
    ClaimAction,
    ClaimStatus,
    DistributionStatus,
    EmployeeModel,
    FeeType,
    FeeVariant,
    FinancialStatus,
    MANAGER_HEADERS,
    OWNER_HEADERS,
    PositionClass,
    ReviewDecision,
    ReviewDimension,
    TestStatus,
    VarianceCategory,
    VarianceDecision,
    VarianceStatus,
    assert_gop_achievement,
    assert_object_envelope,
    assert_page,
    assert_rpi,
    assert_variance_pct,
    budget_decision_payload,
    find_accrual,
    variance_decision_payload,
)


# ---------------------------------------------------------------------------
# The reporting deadline and the strict lateness comparison
# ---------------------------------------------------------------------------


def _due_date_hotel(scenario):
    """Three open periods whose deadlines fall in three different months."""
    agreement = scenario.register(
        hotel_name="Due Date Hotel",
        owner_entity_name="Due Date Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
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

    september = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    october = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=10,
        rooms_revenue_cents=21000000,
        operating_expenses_cents=6000000,
    )
    december = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=12,
        rooms_revenue_cents=22000000,
        operating_expenses_cents=6000000,
    )
    return {
        "agreement_id": agreement["id"],
        "september_id": september["id"],
        "october_id": october["id"],
        "december_id": december["id"],
    }


class TestPackageDueDateAndLatenessBoundary:
    def test_the_deadline_is_the_twenty_fifth_of_the_following_month(self, scenario):
        """PRD §3.4: "The `due_date_utc` — the reporting deadline — is the twenty-fifth day of the
        month following the reported period at midnight UTC; for a period whose `period_month` is
        12, it rolls to the twenty-fifth of January in the following calendar year."

        Design: Corner/calculations/package_due_date_derivation_and_on_time_submission_boundary
        """
        state = _due_date_hotel(scenario)

        assert scenario.read_package(state["september_id"])["due_date_utc"].startswith(
            "2026-10-25T00:00:00"
        )
        assert scenario.read_package(state["october_id"])["due_date_utc"].startswith(
            "2026-11-25T00:00:00"
        )
        assert scenario.read_package(state["december_id"])["due_date_utc"].startswith(
            "2027-01-25T00:00:00"
        )

    def test_a_submit_on_the_deadline_is_on_time_and_one_second_later_is_late(self, scenario):
        """PRD §3.4: "Both origins stamp `submitted_at` with the logical clock and set
        `submitted_late` to true exactly when that instant is strictly after `due_date_utc` — an
        instant equal to the deadline is on time." PRD §2.10: "Every budget in `SUBMITTED` whose
        `owner_decision_deadline_utc` is strictly before the new clock value becomes
        `DEEMED_APPROVED`. The count is reported as `deemed_approved_budget_count`."

        Design: Corner/calculations/package_due_date_derivation_and_on_time_submission_boundary
        """
        state = _due_date_hotel(scenario)

        sweep = scenario.set_clock("2026-10-25T00:00:00Z")
        on_time = scenario.submit_package(state["september_id"])
        scenario.set_clock("2026-11-25T00:00:01Z")
        late = scenario.submit_package(state["october_id"])

        # The only budget was already APPROVED, so step one of the sweep found nothing.
        assert sweep["deemed_approved_budget_count"] == 0
        assert on_time["submitted_at"].startswith("2026-10-25T00:00:00")
        assert on_time["submitted_late"] is False
        assert late["submitted_at"].startswith("2026-11-25T00:00:01")
        assert late["submitted_late"] is True
        # The untouched December period was never stamped at all.
        december = scenario.read_package(state["december_id"])
        assert december["submitted_at"] is None
        assert december["submitted_late"] is False


# ---------------------------------------------------------------------------
# The budget's two different rounding directions
# ---------------------------------------------------------------------------


class TestBudgetDerivedAmountRounding:
    def test_the_allowance_is_floored_while_the_annual_fee_is_rounded_half_up(self, scenario):
        """PRD §3.2: "The budgeted base management fee is the budgeted gross revenue multiplied by
        the agreement's `base_fee_pct`, rounded half up to whole cents" And "The budgeted
        centralized-services charge is taken at the contractual ceiling: the budgeted gross revenue
        multiplied by `centralized_services_cap_pct`, floored to whole cents, stored as
        `budgeted_centralized_cents`." And "The budgeted adjusted gross operating profit,
        `budgeted_agop_cents`, is the budgeted gross revenue less the budgeted operating expenses,
        less the budgeted base fee, less the budgeted centralized charge."

        Design: Corner/calculations/budget_agop_floors_the_centralized_allowance_and_half_ups_the_base_fee
        """
        agreement = scenario.register(
            hotel_name="Single Rounding Hotel",
            owner_entity_name="Rounding Owner LLC",
            base_fee_pct=0.0325,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
            centralized_services_cap_pct=0.015,
        )
        scenario.activate(agreement["id"])

        budget = scenario.budget(
            agreement["id"],
            fiscal_year=2026,
            budgeted_revenue_cents=200000100,
            budgeted_operating_expenses_cents=130000000,
        )

        # 6500003.25 rounds half up to 6500003; 3000001.5 floors to 3000001.
        assert budget["budgeted_base_fee_cents"] == 6500003
        assert budget["budgeted_centralized_cents"] == 3000001
        # A half-up allowance of 3000002 would have left 60500095.
        assert budget["budgeted_agop_cents"] == 60500096
        assert budget["status"] == BudgetStatus.DRAFT
        assert budget["revision_round"] == 0


# ---------------------------------------------------------------------------
# The inclusive upper bound of the manager's own tier
# ---------------------------------------------------------------------------


def _tier_boundary_hotel(scenario):
    """An approved budget whose operating and FF&E lines are both 20000000."""
    agreement = scenario.register(
        hotel_name="Tier Boundary Hotel",
        owner_entity_name="Tier Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=20000000,
        budgeted_capital_ffe_cents=20000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestVarianceTierBoundary:
    def test_a_ratio_of_exactly_five_percent_stays_in_the_managers_hands(self, scenario):
        """PRD §3.3: "Otherwise `variance_pct` is the requested amount divided by the effective
        baseline, rounded to six decimal places." And "A request whose `variance_pct` is at most
        0.05 and whose `requested_amount_cents` is at most 2,500,000 cents — twenty-five thousand
        dollars — is routed to `MANAGER_DISCRETION`; a ratio of exactly 0.05 therefore stays in the
        manager's own hands." And "A `MANAGER_DISCRETION` request needs no decision: it is
        persisted directly in `status` `AUTO_APPROVED`, `decided_by_user_id` stays null, and
        `PENDING` is never observable for it."

        Design: Corner/calculations/variance_tier_at_exactly_five_percent_stays_manager_discretion
        """
        state = _tier_boundary_hotel(scenario)

        at_the_line = scenario.variance(
            state["budget_id"],
            category=VarianceCategory.OPERATING,
            requested_amount_cents=1000001,
            justification="boiler repair at the tier boundary",
        )

        assert at_the_line["effective_baseline_cents"] == 20000000
        # 1000001 / 20000000 is 0.05000005, which rounds to 0.050000 at six places.
        assert_variance_pct(at_the_line["variance_pct"], 0.050000)
        assert at_the_line["approval_level"] == ApprovalLevel.MANAGER_DISCRETION
        assert at_the_line["status"] == VarianceStatus.AUTO_APPROVED
        assert at_the_line["decided_by_user_id"] is None

    def test_one_step_over_the_line_needs_the_asset_manager(self, scenario):
        """PRD §3.3: "Failing that, a request whose `variance_pct` is at most 0.15 and whose
        `requested_amount_cents` is at most 25,000,000 cents — a quarter of a million dollars — is
        routed to `ASSET_MANAGER`." And "Requests routed to `ASSET_MANAGER` or `OWNER_REP` are
        persisted in `PENDING` and wait."

        Design: Corner/calculations/variance_tier_at_exactly_five_percent_stays_manager_discretion
        """
        state = _tier_boundary_hotel(scenario)
        scenario.variance(
            state["budget_id"],
            category=VarianceCategory.OPERATING,
            requested_amount_cents=1000001,
            justification="boiler repair at the tier boundary",
        )

        over_the_line = scenario.variance(
            state["budget_id"],
            category=VarianceCategory.CAPITAL_FFE,
            requested_amount_cents=1010000,
            justification="guestroom soft goods top-up just over the tier",
        )

        # The approved OPERATING sibling raises no CAPITAL_FFE baseline.
        assert over_the_line["effective_baseline_cents"] == 20000000
        assert_variance_pct(over_the_line["variance_pct"], 0.050500)
        assert over_the_line["approval_level"] == ApprovalLevel.ASSET_MANAGER
        assert over_the_line["status"] == VarianceStatus.PENDING


# ---------------------------------------------------------------------------
# Which siblings raise the baseline for the next request
# ---------------------------------------------------------------------------


def _baseline_filter_hotel(scenario):
    """One auto-approved and one denied OPERATING sibling on a 20000000 line."""
    agreement = scenario.register(
        hotel_name="Baseline Filter Hotel",
        owner_entity_name="Baseline Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=20000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    approved = scenario.variance(
        budget["id"],
        category=VarianceCategory.OPERATING,
        requested_amount_cents=1000001,
        justification="first approved top-up",
    )
    refused = scenario.variance(
        budget["id"],
        category=VarianceCategory.OPERATING,
        requested_amount_cents=30000000,
        justification="rejected repositioning programme",
    )
    denied = assert_object_envelope(
        scenario.api.decide_variance_request(
            refused["id"],
            variance_decision_payload(VarianceDecision.DENY, note="out of scope this year"),
            OWNER_HEADERS,
        ),
        200,
    )
    return {
        "budget_id": budget["id"],
        "approved_id": approved["id"],
        "denied": denied,
    }


class TestVarianceBaselineInputSet:
    def test_only_the_approved_sibling_raises_the_baseline(self, scenario):
        """PRD §3.3: "To that is added the accumulated authority already granted: the sum of
        `requested_amount_cents` over sibling variance requests carrying the same `budget_id` and
        the same `category` whose `status` is `AUTO_APPROVED` or `APPROVED` and whose `created_at`
        is strictly earlier than this row's. The total is stored as `effective_baseline_cents`."

        Design: Corner/calculations/variance_baseline_counts_approved_siblings_but_not_denied_ones
        """
        state = _baseline_filter_hotel(scenario)
        assert state["denied"]["status"] == VarianceStatus.DENIED
        assert state["denied"]["denied_by_cascade"] is False

        third = scenario.variance(
            state["budget_id"],
            category=VarianceCategory.OPERATING,
            requested_amount_cents=1050001,
            justification="third request measured against the raised baseline",
        )

        # 20000000 plus the auto-approved 1000001, and not the denied 30000000.
        assert third["effective_baseline_cents"] == 21000001
        assert_variance_pct(third["variance_pct"], 0.050000)
        assert third["approval_level"] == ApprovalLevel.MANAGER_DISCRETION
        assert third["status"] == VarianceStatus.AUTO_APPROVED

    def test_the_denied_sibling_still_lists_under_its_category(self, scenario):
        """PRD §3.3: "the difference between them is only that an approval raises the effective
        baseline for later siblings while a denial does not." And "Variance requests raised against
        a budget can be listed by any role, filterable by `category` and by `status`."

        Design: Corner/calculations/variance_baseline_counts_approved_siblings_but_not_denied_ones
        """
        state = _baseline_filter_hotel(scenario)
        scenario.variance(
            state["budget_id"],
            category=VarianceCategory.OPERATING,
            requested_amount_cents=1050001,
            justification="third request measured against the raised baseline",
        )

        rows = assert_page(
            scenario.api.list_variance_requests(
                state["budget_id"], ASSET_HEADERS, {"category": VarianceCategory.OPERATING}
            ),
            expected_rows=3,
            total_count=3,
            has_more=False,
        )
        assert [row["status"] for row in rows] == [
            VarianceStatus.AUTO_APPROVED,
            VarianceStatus.DENIED,
            VarianceStatus.AUTO_APPROVED,
        ]


# ---------------------------------------------------------------------------
# The true-up's two input sets: accepted periods and live provisional accruals
# ---------------------------------------------------------------------------


def _true_up_filter_hotel(scenario):
    """One accepted September period beside a disputed October one."""
    agreement = scenario.register(
        hotel_name="True Up Filter Hotel",
        owner_entity_name="True Up Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        incentive_tier2_pct=0.15,
        incentive_tier2_threshold_cents=5000000,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0,
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

    accepted = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(accepted["id"])
    scenario.review_package(accepted["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

    disputed = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=10,
        rooms_revenue_cents=10000000,
        fnb_revenue_cents=0,
        other_revenue_cents=0,
        operating_expenses_cents=3000000,
    )
    scenario.submit_package(disputed["id"])
    scenario.review_package(disputed["id"], ReviewDimension.FINANCIAL, ReviewDecision.DISPUTE)

    return {
        "agreement_id": agreement["id"],
        "accepted_id": accepted["id"],
        "disputed_id": disputed["id"],
    }


class TestAnnualTrueUpInputSets:
    def test_only_accepted_periods_enter_the_annual_profit(self, scenario):
        """PRD §3.8: "The eligible periods are that agreement's report packages whose
        `fiscal_year` matches the request and whose `financial_status` is `ACCEPTED`. Periods in
        `DISPUTED`, `SUBMITTED` and `PENDING` are all excluded, and a fiscal year with no accepted
        period is refused with `ERR_NO_ACCEPTED_PERIODS`. Their count is reported as
        `accepted_period_count` and `annual_agop_cents` is the sum of `agop_cents` over them"

        Design: Corner/calculations/annual_true_up_counts_only_accepted_periods_and_live_accruals
        """
        state = _true_up_filter_hotel(scenario)
        # The disputed period computed its own profit and keeps it on the row.
        assert scenario.read_package(state["disputed_id"])["agop_cents"] == 6700000

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["accepted_period_count"] == 1
        assert summary["annual_agop_cents"] == 20220000
        # 10 percent of the first 5000000 of excess plus 15 percent of the next 3220000.
        assert summary["final_incentive_fee_cents"] == 983000
        assert summary["attached_report_package_id"] == state["accepted_id"]

    def test_the_reversed_provisional_accrual_never_enters_the_collected_total(self, scenario):
        """PRD §3.8: "What the manager has already collected is
        `provisional_incentive_total_cents`: the sum of `amount_cents` over that agreement's fee
        accruals for the same `fiscal_year` whose `fee_type` is `INCENTIVE`, whose `variant` is
        `PROVISIONAL`, and whose `status` is `ACCRUED`, `INVOICED` or `PAID`. A provisional accrual
        that was reversed by a disputed package never enters that total, and neither does one
        sitting in `DISPUTED_HELD`."

        Design: Corner/calculations/annual_true_up_counts_only_accepted_periods_and_live_accruals
        """
        state = _true_up_filter_hotel(scenario)
        stranded = find_accrual(
            scenario.accruals(state["disputed_id"]),
            FeeType.INCENTIVE,
            FeeVariant.PROVISIONAL,
        )
        assert stranded["amount_cents"] == 570000
        assert stranded["status"] == AccrualStatus.REVERSED

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["provisional_incentive_total_cents"] == 1922000
        assert summary["true_up_delta_cents"] == -939000
        final_rows = assert_page(
            scenario.api.list_fee_accruals(
                state["accepted_id"], ASSET_HEADERS, {"variant": FeeVariant.FINAL}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert final_rows[0]["id"] == summary["true_up_accrual_id"]


# ---------------------------------------------------------------------------
# The fixed bucket order and what it starves
# ---------------------------------------------------------------------------


def _waterfall_order_hotel(scenario):
    """An accepted period holding 1500000 of cash against 4742000 of demand."""
    agreement = scenario.register(
        hotel_name="Waterfall Order Hotel",
        owner_entity_name="Waterfall Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        working_capital_floor_cents=0,
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

    package = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=9,
        closing_cash_available_cents=1500000,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    distribution = scenario.only_distribution(package["id"])
    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "distribution_id": distribution["id"],
    }


class TestWaterfallBucketOrder:
    def test_the_fixed_order_pays_the_fee_part_funds_the_reserve_and_starves_the_rest(
        self, scenario
    ):
        """PRD §3.6: "Cash is then allocated in a fixed order, each bucket taking the smaller of
        the cash still unallocated and its own demand, and each allocation reducing what remains
        for the next." And "Note the ordering consequence the owner should understand: the reserve
        contribution outranks the owner's own priority return, and the manager's incentive fee
        ranks below both."

        Design: Corner/calculations/waterfall_bucket_order_starves_the_lower_buckets
        """
        state = _waterfall_order_hotel(scenario)

        executed = assert_object_envelope(
            scenario.api.execute_distribution(state["distribution_id"], MANAGER_HEADERS), 200
        )

        assert executed["status"] == DistributionStatus.EXECUTED
        assert executed["available_cash_cents"] == 1500000
        assert executed["wc_restoration_cents"] == 0
        assert executed["base_fee_paid_cents"] == 780000
        # 1040000 was demanded, 720000 of cash survived the base fee.
        assert executed["reserve_contribution_cents"] == 720000
        assert executed["owner_priority_paid_cents"] == 0
        assert executed["incentive_fee_paid_cents"] == 0
        assert executed["residual_to_owner_cents"] == 0
        # 4742000 demanded less 1500000 allocated.
        assert executed["shortfall_cents"] == 3242000

    def test_the_part_funded_reserve_and_the_shortfall_call_follow_the_allocation(self, scenario):
        """PRD §3.6: "a reserve ledger entry is appended with `entry_type` `CONTRIBUTION`,
        `amount_cents` equal to `reserve_contribution_cents` and `source_kind`
        `DISTRIBUTION_EXECUTION`, with the agreement's `ffe_reserve_balance_cents` increased by the
        same amount" And "a call with `reason` `DISTRIBUTION_SHORTFALL`, `amount_cents` equal to
        the distribution's `shortfall_cents`, `auto_created` set to true and `status` `REQUESTED`."
        PRD §3.6: "Every call, however raised, has its `due_date_utc` set to the logical clock at
        the moment of issue advanced by the agreement's `funding_due_days`."

        Design: Corner/calculations/waterfall_bucket_order_starves_the_lower_buckets
        """
        state = _waterfall_order_hotel(scenario)

        scenario.execute_distribution(state["distribution_id"])

        entries = scenario.ledger(state["agreement_id"])
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 720000
        assert entries[0]["balance_after_cents"] == 720000
        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 720000

        rows = assert_page(
            scenario.api.list_working_capital_calls(state["agreement_id"], ASSET_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["reason"] == CallReason.DISTRIBUTION_SHORTFALL
        assert rows[0]["amount_cents"] == 3242000
        assert rows[0]["auto_created"] is True
        assert rows[0]["status"] == CallStatus.REQUESTED
        assert rows[0]["due_date_utc"].startswith("2026-08-16T00:00:00")

        # The base fee was paid in full while the starved incentive bucket moved nothing.
        accruals = scenario.accruals(state["package_id"])
        base = find_accrual(accruals, FeeType.BASE, FeeVariant.PROVISIONAL)
        assert base["status"] == AccrualStatus.PAID
        assert base["paid_amount_cents"] == 780000
        incentive = find_accrual(accruals, FeeType.INCENTIVE, FeeVariant.PROVISIONAL)
        assert incentive["paid_amount_cents"] == 0


# ---------------------------------------------------------------------------
# Only the live benchmark row scores the index
# ---------------------------------------------------------------------------


def _superseded_benchmark_hotel(scenario):
    """A challenged 83.33 benchmark replaced by a 91.67 one, then accepted."""
    agreement = scenario.register(
        hotel_name="Superseded Benchmark Hotel",
        owner_entity_name="Benchmark Owner LLC",
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
    challenged = scenario.benchmark(package["id"])
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.DISPUTE)
    replacement = scenario.benchmark(package["id"], hotel_revpar_cents=11000)
    scenario.review_package(package["id"], ReviewDimension.BENCHMARK, ReviewDecision.ACCEPT)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)

    return {
        "agreement_id": agreement["id"],
        "package_id": package["id"],
        "challenged_id": challenged["id"],
        "replacement_id": replacement["id"],
    }


class TestReplacementBenchmarkScoring:
    def test_the_replacement_supersedes_the_challenged_row_and_owns_the_reported_index(
        self, scenario
    ):
        """PRD §3.7: "Posting is admissible from `benchmark_status` `PENDING → SUBMITTED`, which
        sets the package's `reported_rpi` to the new row's `rpi`, and from `CHALLENGED →
        SUBMITTED`, which first marks the package's previous non-superseded benchmark with
        `superseded` true, then creates the new row and replaces the package's `reported_rpi` with
        the new index."

        Design: Corner/calculations/replacement_benchmark_supersedes_the_challenged_row_before_scoring
        """
        state = _superseded_benchmark_hotel(scenario)

        rows = {row["id"]: row for row in scenario.benchmarks(state["package_id"])}

        assert_rpi(rows[state["challenged_id"]]["rpi"], 83.33)
        assert rows[state["challenged_id"]]["superseded"] is True
        assert_rpi(rows[state["replacement_id"]]["rpi"], 91.67)
        assert rows[state["replacement_id"]]["superseded"] is False
        assert_page(
            scenario.api.list_benchmarks(
                state["package_id"], ASSET_HEADERS, {"superseded": "true"}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert_rpi(scenario.read_package(state["package_id"])["reported_rpi"], 91.67)

    def test_the_live_row_alone_scores_the_index_and_saves_the_test(self, scenario):
        """PRD §3.7: "The benchmark leg draws on a deliberately narrow input set: benchmarks
        sitting on those same accepted periods whose `source` is `STR_REPORT`, whose `superseded`
        is false, and whose package's `benchmark_status` is `ACCEPTED`." And "Where the test does
        not fail, its `status` is `PASSED`, `streak_after_test` is 0, `cure_payment_due_cents` is
        0, `cure_deadline_utc` stays null, and the agreement's `performance_failure_streak` is
        reset to 0."

        Design: Corner/calculations/replacement_benchmark_supersedes_the_challenged_row_before_scoring
        """
        state = _superseded_benchmark_hotel(scenario)

        test = scenario.performance_test(state["agreement_id"], 2026)

        assert test["str_month_count"] == 1
        assert_rpi(test["rpi_weighted"], 91.67)
        assert_rpi(test["rpi_simple_average"], 91.67)
        assert test["prorated_budget_agop_cents"] == 86500000
        assert test["actual_agop_cents"] == 20220000
        assert_gop_achievement(test["gop_achievement_pct"], 0.2338)
        # The AGOP leg failed, but 91.67 clears 90.0 and a single passing leg saves the test.
        assert test["status"] == TestStatus.PASSED
        assert test["streak_after_test"] == 0
        assert test["cure_payment_due_cents"] == 0
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["status"] == AgreementStatus.ACTIVE
        assert agreement["performance_failure_streak"] == 0
        assert agreement["distribution_hold"] is False


# ---------------------------------------------------------------------------
# The negligence override outranks the position class
# ---------------------------------------------------------------------------


class TestGrossNegligenceOverride:
    def test_negligence_puts_the_whole_claim_on_the_manager_up_to_the_cap(self, scenario):
        """PRD §3.9: "Where `gross_negligence` is true, the manager bears the whole claim up to
        the cap: `manager_share_cents` is the smaller of `claim_amount_cents` and the agreement's
        `manager_indemnity_cap_cents`. This negligence override ignores both the position class
        and the employee model entirely" And "In every branch `owner_share_cents` is
        `claim_amount_cents` less `manager_share_cents`, which makes the conservation invariant
        exact: the two shares always sum to `claim_amount_cents`, with no rounding remainder
        anywhere."

        Design: Corner/calculations/gross_negligence_selects_the_override_split_variant
        """
        agreement = scenario.register(
            hotel_name="Negligence Override Hotel",
            owner_entity_name="Override Owner LLC",
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
            employee_model=EmployeeModel.MANAGER_EMPLOYEES,
            manager_indemnity_cap_cents=2000000,
            initial_working_capital_cents=5000000,
            working_capital_floor_cents=0,
        )
        scenario.activate(agreement["id"])
        claim = scenario.claim(
            agreement["id"],
            position_class=PositionClass.GM,
            claim_amount_cents=3000001,
            gross_negligence=True,
        )

        allocated = scenario.allocate_claim(claim["id"], ClaimAction.ALLOCATE)

        assert allocated["status"] == ClaimStatus.ALLOCATED
        # The even GM split would have been 1500000 / 1500001.
        assert allocated["manager_share_cents"] == 2000000
        assert allocated["owner_share_cents"] == 1000001
        assert allocated["manager_share_cents"] + allocated["owner_share_cents"] == 3000001
        parent = scenario.read_agreement(agreement["id"])
        assert parent["working_capital_balance_cents"] == 3999999
        assert parent["manager_liability_accrued_cents"] == 2000000
        # PRD §3.9: the second hop is skipped when the balance still meets the floor.
        assert_page(
            scenario.api.list_working_capital_calls(agreement["id"], ASSET_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# The deadlock with an empty carry-forward candidate set
# ---------------------------------------------------------------------------


def _empty_fallback_hotel(scenario):
    """A first revision request against max_revision_rounds 0 and no prior year."""
    agreement = scenario.register(
        hotel_name="Empty Fallback Hotel",
        owner_entity_name="Fallback Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        max_revision_rounds=0,
        centralized_services_cap_pct=0.015,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
        budgeted_capital_ffe_cents=4000000,
        budgeted_capital_brand_cents=2000000,
    )
    scenario.submit_budget(budget["id"])
    return {"agreement_id": agreement["id"], "budget_id": budget["id"]}


class TestDeadlockCarryforwardWithNoPriorYear:
    def test_the_empty_candidate_set_leaves_the_submitted_amounts_standing(self, scenario):
        """PRD §3.2: "When `revision_round` has reached or passed `max_revision_rounds`, a further
        revision request deadlocks: the row moves `SUBMITTED → DEADLOCK_CARRYFORWARD`,
        `carryforward_applied` is set to true, and the four budgeted input amounts are" And "If no
        eligible prior-year candidate exists at all, the last submitted amounts stand unchanged and
        `carryforward_applied` is left false. Either way, `budgeted_base_fee_cents`,
        `budgeted_centralized_cents` and `budgeted_agop_cents` are then recomputed from whatever
        amounts now stand."

        Design: Corner/calculations/deadlock_carryforward_with_no_prior_year_leaves_the_amounts_unchanged
        """
        state = _empty_fallback_hotel(scenario)

        deadlocked = assert_object_envelope(
            scenario.api.decide_budget(
                state["budget_id"],
                budget_decision_payload(BudgetDecision.REQUEST_REVISION),
                OWNER_HEADERS,
            ),
            200,
        )

        assert deadlocked["status"] == BudgetStatus.DEADLOCK_CARRYFORWARD
        assert deadlocked["revision_round"] == 0
        assert deadlocked["carryforward_applied"] is False
        # No 1.03 uplift was applied, so revenue is not 309000000.
        assert deadlocked["budgeted_revenue_cents"] == 300000000
        assert deadlocked["budgeted_operating_expenses_cents"] == 200000000
        assert deadlocked["budgeted_capital_ffe_cents"] == 4000000
        assert deadlocked["budgeted_capital_brand_cents"] == 2000000
        assert deadlocked["budgeted_base_fee_cents"] == 9000000
        assert deadlocked["budgeted_centralized_cents"] == 4500000
        assert deadlocked["budgeted_agop_cents"] == 86500000
        assert deadlocked["decided_by_user_id"] == "u-owner-1"

    def test_the_deadlocked_year_still_counts_as_approved_for_a_period_submit(self, scenario):
        """PRD §2.8 rule 40: "A budget of the same agreement and `fiscal_year` holds `APPROVED`,
        `DEEMED_APPROVED` or `DEADLOCK_CARRYFORWARD`; otherwise `ERR_BUDGET_NOT_APPROVED` (422)."

        Design: Corner/calculations/deadlock_carryforward_with_no_prior_year_leaves_the_amounts_unchanged
        """
        state = _empty_fallback_hotel(scenario)
        scenario.api.decide_budget(
            state["budget_id"],
            budget_decision_payload(BudgetDecision.REQUEST_REVISION),
            OWNER_HEADERS,
        )

        package = scenario.package(state["agreement_id"], fiscal_year=2026, period_month=9)
        submitted = assert_object_envelope(
            scenario.api.submit_report_package(package["id"], MANAGER_HEADERS), 200
        )

        assert submitted["financial_status"] == FinancialStatus.SUBMITTED
        assert submitted["base_fee_cents"] == 780000
        assert submitted["agop_cents"] == 20220000
