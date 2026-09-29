"""Endpoint surface: list filters, the clock envelope, link targets and projections."""

from test_helpers import (
    ADMIN_HEADERS,
    ASSET_HEADERS,
    AgreementStatus,
    ApiErrorId,
    BudgetDecision,
    BudgetStatus,
    CallReason,
    CallStatus,
    FeeType,
    FeeVariant,
    MANAGER_HEADERS,
    OWNER_HEADERS,
    ReviewDecision,
    ReviewDimension,
    TRUE_UP_SUMMARY_KEYS,
    TestStatus,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    budget_payload,
    elect_cure_payload,
    fund_payload,
    pay_cure_payload,
    true_up_payload,
)


# ---------------------------------------------------------------------------
# The cross-agreement budget list
# ---------------------------------------------------------------------------


def _list_filter_hotels(scenario):
    """Agreement L holds three budgets in three years and three statuses; M holds one."""
    lead = scenario.register(
        hotel_name="List Filter Hotel L",
        owner_entity_name="Filter Owner L LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(lead["id"])
    approved = scenario.budget(
        lead["id"],
        fiscal_year=2025,
        budgeted_revenue_cents=280000000,
        budgeted_operating_expenses_cents=190000000,
    )
    scenario.submit_budget(approved["id"])
    scenario.decide_budget(approved["id"], BudgetDecision.APPROVE)
    draft = scenario.budget(
        lead["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    submitted = scenario.budget(
        lead["id"],
        fiscal_year=2027,
        budgeted_revenue_cents=320000000,
        budgeted_operating_expenses_cents=210000000,
    )
    scenario.submit_budget(submitted["id"])

    other = scenario.register(
        hotel_name="List Filter Hotel M",
        owner_entity_name="Filter Owner M LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(other["id"])
    other_draft = scenario.budget(
        other["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=150000000,
        budgeted_operating_expenses_cents=100000000,
    )
    return {
        "lead_id": lead["id"],
        "approved_id": approved["id"],
        "draft_id": draft["id"],
        "submitted_id": submitted["id"],
        "other_draft_id": other_draft["id"],
    }


class TestBudgetListFilters:
    def test_agreement_and_fiscal_year_narrow_along_different_axes(self, scenario):
        """PRD §3.2: "Budget revisions can be read individually and listed. The list is filterable
        by `agreement_id`, by `supersedes_budget_id` — which is how a reader reconstructs a revision
        chain — by `fiscal_year` and by `status`" PRD §2.3: "`total_count` counts every row matching
        the filters before paging is applied"

        Design: Corner/endpoints/budget_list_filters_by_agreement_fiscal_year_and_status
        """
        state = _list_filter_hotels(scenario)

        by_agreement = assert_page(
            scenario.api.list_budgets(ASSET_HEADERS, {"agreement_id": state["lead_id"]}),
            expected_rows=3,
            total_count=3,
            has_more=False,
        )
        by_year = assert_page(
            scenario.api.list_budgets(ASSET_HEADERS, {"fiscal_year": 2026}),
            expected_rows=2,
            total_count=2,
            has_more=False,
        )

        assert {row["id"] for row in by_agreement} == {
            state["approved_id"],
            state["draft_id"],
            state["submitted_id"],
        }
        # The year filter reaches across agreements the agreement filter excluded.
        assert {row["id"] for row in by_year} == {state["draft_id"], state["other_draft_id"]}

    def test_status_narrows_further_and_an_unsatisfiable_combination_returns_no_rows(
        self, scenario
    ):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the
        `meta` object of the envelope" PRD §3.2: "The `REVISION_REQUESTED` origin additionally
        increments `revision_round` by one; the `DRAFT` origin does not, leaving `revision_round` at
        its opening value of 0."

        Design: Corner/endpoints/budget_list_filters_by_agreement_fiscal_year_and_status
        """
        state = _list_filter_hotels(scenario)

        only_submitted = assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS,
                {"agreement_id": state["lead_id"], "status": BudgetStatus.SUBMITTED},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        empty = assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS,
                {
                    "agreement_id": state["lead_id"],
                    "fiscal_year": 2026,
                    "status": BudgetStatus.APPROVED,
                },
            ),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )

        assert only_submitted[0]["id"] == state["submitted_id"]
        # FY2026 on agreement L is DRAFT, so the three filters cannot be satisfied together.
        assert empty == []
        assert scenario.read_budget(state["approved_id"])["status"] == BudgetStatus.APPROVED
        assert scenario.read_budget(state["draft_id"])["status"] == BudgetStatus.DRAFT
        assert scenario.read_budget(state["submitted_id"])["status"] == BudgetStatus.SUBMITTED
        for budget_id in (state["approved_id"], state["draft_id"], state["submitted_id"]):
            assert scenario.read_budget(budget_id)["revision_round"] == 0


# ---------------------------------------------------------------------------
# One clock move, five counters
# ---------------------------------------------------------------------------


def _sweep_counter_hotel(scenario):
    """A budget awaiting a decision and a call awaiting funding, both dated August."""
    agreement = scenario.register(
        hotel_name="Sweep Counter Hotel",
        owner_entity_name="Sweep Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        owner_review_window_days=30,
        funding_due_days=15,
        initial_working_capital_cents=0,
        working_capital_floor_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    call = scenario.call(
        agreement["id"], amount_cents=500000, reason=CallReason.FLOOR_RESTORATION
    )
    return {
        "agreement_id": agreement["id"],
        "budget_id": budget["id"],
        "call_id": call["id"],
    }


class TestClockAdvanceReportsEverySweepCounter:
    def test_every_counter_is_present_and_the_two_non_zero_ones_match_the_rows(self, scenario):
        """PRD §2.4: "A `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the
        clock-control operation, whose response reports the new `current_utc` together with the
        counts of rows the move swept: `deemed_approved_budget_count`, `overdue_call_count`,
        `lapsed_cure_count`, `deadlocked_dispute_count` and `terminated_agreement_count`." PRD
        §2.10: "Every budget in `SUBMITTED` whose `owner_decision_deadline_utc` is strictly before
        the new clock value becomes `DEEMED_APPROVED`."

        Design: Corner/endpoints/clock_advance_reports_every_sweep_counter
        """
        state = _sweep_counter_hotel(scenario)

        sweep = assert_object_envelope(
            scenario.api.set_clock("2026-09-01T00:00:00Z", ADMIN_HEADERS), 200
        )

        assert sweep["current_utc"].startswith("2026-09-01T00:00:00")
        assert sweep["deemed_approved_budget_count"] == 1
        assert sweep["overdue_call_count"] == 1
        assert sweep["lapsed_cure_count"] == 0
        assert sweep["deadlocked_dispute_count"] == 0
        assert sweep["terminated_agreement_count"] == 0
        budget = scenario.read_budget(state["budget_id"])
        assert budget["status"] == BudgetStatus.DEEMED_APPROVED
        assert budget["decided_by_user_id"] is None
        assert scenario.only_call(state["agreement_id"])["status"] == CallStatus.OVERDUE

    def test_the_swept_call_funds_late_and_still_credits_the_account(self, scenario):
        """PRD §3.6: "or from `OVERDUE → FUNDED`, which does exactly the same" PRD §2.9:
        "`working_capital_balance_cents` is seeded from `initial_working_capital_cents` at
        activation and thereafter moves only through funded calls, the first bucket of an executed
        distribution, a paid cure and employment-claim allocations"

        Design: Corner/endpoints/clock_advance_reports_every_sweep_counter
        """
        state = _sweep_counter_hotel(scenario)
        scenario.set_clock("2026-09-01T00:00:00Z")

        funded = assert_object_envelope(
            scenario.api.fund_working_capital_call(
                state["call_id"], fund_payload(500000), OWNER_HEADERS
            ),
            200,
        )

        assert funded["status"] == CallStatus.FUNDED
        assert funded["funded_amount_cents"] == 500000
        # The owner's tardiness is on the record.
        assert funded["late_funded"] is True
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["working_capital_balance_cents"] == 500000
        assert agreement["status"] == AgreementStatus.ACTIVE


# ---------------------------------------------------------------------------
# A supersede target from the wrong agreement
# ---------------------------------------------------------------------------


def _supersede_hotels(scenario):
    """Two agreements, each holding its own SUBMITTED FY2026 revision."""
    state = {}
    for key, hotel, owner, revenue, opex in (
        ("p", "Supersede Hotel P", "Supersede Owner P LLC", 300000000, 200000000),
        ("q", "Supersede Hotel Q", "Supersede Owner Q LLC", 150000000, 100000000),
    ):
        agreement = scenario.register(
            hotel_name=hotel,
            owner_entity_name=owner,
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
        )
        scenario.activate(agreement["id"])
        budget = scenario.budget(
            agreement["id"],
            fiscal_year=2026,
            budgeted_revenue_cents=revenue,
            budgeted_operating_expenses_cents=opex,
        )
        scenario.submit_budget(budget["id"])
        state[key + "_agreement_id"] = agreement["id"]
        state[key + "_budget_id"] = budget["id"]
    return state


def _revision_body(version, supersedes_budget_id):
    return budget_payload(
        version,
        fiscal_year=2026,
        budgeted_revenue_cents=305000000,
        budgeted_operating_expenses_cents=201000000,
        supersedes_budget_id=supersedes_budget_id,
    )


class TestSupersedeTargetMustBelongToTheSameAgreement:
    def test_a_foreign_target_is_refused_and_burns_no_agreement_version(self, scenario):
        """PRD §2.8 rule 16: "When `supersedes_budget_id` is present it names a budget of the same
        agreement and the same `fiscal_year` whose `status` is `DRAFT`, `SUBMITTED` or
        `REVISION_REQUESTED`; otherwise `ERR_SUPERSEDE_TARGET_INVALID` (422)." PRD §3.2: "A
        supersede target belonging to another agreement or another fiscal year, or already sitting
        in one of the four terminal budget statuses, is refused with
        `ERR_SUPERSEDE_TARGET_INVALID`."

        Design: Corner/endpoints/supersedes_budget_id_pointing_at_another_agreement_rejected
        """
        state = _supersede_hotels(scenario)
        version = scenario.agreement_version(state["p_agreement_id"])

        refused = scenario.api.create_budget(
            state["p_agreement_id"],
            _revision_body(version, state["q_budget_id"]),
            MANAGER_HEADERS,
        )

        assert_error_envelope(refused, ApiErrorId.SUPERSEDE_TARGET_INVALID)
        assert refused.status_code == 422
        assert scenario.read_budget(state["q_budget_id"])["status"] == BudgetStatus.SUBMITTED
        # Nothing was persisted, so the same version pin is still current.
        assert scenario.agreement_version(state["p_agreement_id"]) == version
        accepted = assert_object_envelope(
            scenario.api.create_budget(
                state["p_agreement_id"],
                _revision_body(version, state["p_budget_id"]),
                MANAGER_HEADERS,
            ),
            201,
        )
        assert accepted["supersedes_budget_id"] == state["p_budget_id"]
        assert accepted["status"] == BudgetStatus.DRAFT

    def test_the_legal_target_is_superseded_and_the_chain_reads_back(self, scenario):
        """PRD §3.2: "When `supersedes_budget_id` is present, the named row moves to `SUPERSEDED` —
        from `DRAFT → SUPERSEDED`, from `SUBMITTED → SUPERSEDED`, or from
        `REVISION_REQUESTED → SUPERSEDED` — with no ledger effect in any of the three cases" And
        "The list is filterable by `agreement_id`, by `supersedes_budget_id` — which is how a
        reader reconstructs a revision chain"

        Design: Corner/endpoints/supersedes_budget_id_pointing_at_another_agreement_rejected
        """
        state = _supersede_hotels(scenario)
        version = scenario.agreement_version(state["p_agreement_id"])
        replacement = assert_object_envelope(
            scenario.api.create_budget(
                state["p_agreement_id"],
                _revision_body(version, state["p_budget_id"]),
                MANAGER_HEADERS,
            ),
            201,
        )

        chain = assert_page(
            scenario.api.list_budgets(
                ASSET_HEADERS, {"supersedes_budget_id": state["p_budget_id"]}
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )

        assert scenario.read_budget(state["p_budget_id"])["status"] == BudgetStatus.SUPERSEDED
        assert chain[0]["id"] == replacement["id"]
        assert scenario.agreement_version(state["p_agreement_id"]) == version + 1


# ---------------------------------------------------------------------------
# Two actions, one endpoint, different origins
# ---------------------------------------------------------------------------


def _cure_order_hotel(scenario):
    """A FAILED_CURABLE test that has not yet been elected for cure."""
    agreement = scenario.register(
        hotel_name="Cure Order Hotel",
        owner_entity_name="Order Owner LLC",
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
    return {"agreement_id": agreement["id"], "test_id": test["id"], "test": test}


class TestCureEndpointRequiresElectionBeforePayment:
    def test_paying_before_electing_is_refused_on_the_state_guard(self, scenario):
        """PRD §2.8 rule 26: "The performance test's `status` is one the requested cure or
        termination transition declares as its origin; otherwise `ERR_INVALID_TEST_STATE` (409)."
        PRD §3.7: "A `PAY_CURE` action moves the test `CURE_ELECTED → CURED` and requires
        `payment_amount_cents` to be at least `cure_payment_due_cents`"

        Design: Corner/endpoints/cure_endpoint_requires_election_before_payment
        """
        state = _cure_order_hotel(scenario)
        assert state["test"]["status"] == TestStatus.FAILED_CURABLE
        assert state["test"]["cure_payment_due_cents"] == 66280000

        response = scenario.api.cure_performance_test(
            state["test_id"], pay_cure_payload(66280000), MANAGER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.INVALID_TEST_STATE)
        assert response.status_code == 409
        assert scenario.performance_tests(state["agreement_id"])[0]["status"] == (
            TestStatus.FAILED_CURABLE
        )
        agreement = scenario.read_agreement(state["agreement_id"])
        assert agreement["working_capital_balance_cents"] == 0
        assert agreement["status"] == AgreementStatus.CURE_PERIOD
        assert agreement["distribution_hold"] is True

    def test_the_election_opens_the_payment_and_the_cured_test_closes_it_again(self, scenario):
        """PRD §3.7: "An `ELECT_CURE` action moves the test `FAILED_CURABLE → CURE_ELECTED` and
        moves no cash — it merely records that the manager intends to cure." And "A sufficient
        payment writes `cure_paid_cents` as the amount paid" And "`PASSED`, `CURED` and
        `TERMINATED_NOTICE_ISSUED` are the terminal test outcomes."

        Design: Corner/endpoints/cure_endpoint_requires_election_before_payment
        """
        state = _cure_order_hotel(scenario)
        scenario.api.cure_performance_test(
            state["test_id"], pay_cure_payload(66280000), MANAGER_HEADERS
        )

        elected = assert_object_envelope(
            scenario.api.cure_performance_test(
                state["test_id"], elect_cure_payload(), MANAGER_HEADERS
            ),
            200,
        )
        cured = assert_object_envelope(
            scenario.api.cure_performance_test(
                state["test_id"], pay_cure_payload(66280000), MANAGER_HEADERS
            ),
            200,
        )
        replayed_election = scenario.api.cure_performance_test(
            state["test_id"], elect_cure_payload(), MANAGER_HEADERS
        )

        assert elected["status"] == TestStatus.CURE_ELECTED
        assert elected["cure_deadline_utc"].startswith("2026-09-30T00:00:00")
        assert cured["status"] == TestStatus.CURED
        assert cured["cure_paid_cents"] == 66280000
        assert_error_envelope(replayed_election, ApiErrorId.INVALID_TEST_STATE)
        assert replayed_election.status_code == 409


# ---------------------------------------------------------------------------
# A projection rather than an entity
# ---------------------------------------------------------------------------


def _true_up_projection_hotel(scenario):
    """One accepted September period against an approved FY2026 budget."""
    agreement = scenario.register(
        hotel_name="True Up Projection Hotel",
        owner_entity_name="Projection Owner LLC",
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
    package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestAnnualTrueUpReturnsAComputedProjection:
    def test_the_summary_carries_exactly_the_eight_declared_keys(self, scenario):
        """PRD §3.8: "The run returns a settlement summary rather than an entity: `fiscal_year`,
        `accepted_period_count`, `annual_agop_cents`, `final_incentive_fee_cents`,
        `provisional_incentive_total_cents`, `true_up_delta_cents`, the identifier of the accrual
        just written as `true_up_accrual_id`, and the identifier of the period it was attached to as
        `attached_report_package_id`."

        Design: Corner/endpoints/annual_true_up_returns_a_computed_projection
        """
        state = _true_up_projection_hotel(scenario)
        version = scenario.agreement_version(state["agreement_id"])

        summary = assert_object_envelope(
            scenario.api.run_annual_true_up(
                state["agreement_id"], true_up_payload(version, 2026), MANAGER_HEADERS
            ),
            200,
        )

        assert set(summary) == TRUE_UP_SUMMARY_KEYS
        assert summary["fiscal_year"] == 2026
        assert summary["accepted_period_count"] == 1
        assert summary["attached_report_package_id"] == state["package_id"]

    def test_the_signed_delta_settles_the_monthly_over_collection(self, scenario):
        """PRD §3.8: "The settlement figure `true_up_delta_cents` is
        `final_incentive_fee_cents` less `provisional_incentive_total_cents`, and it is signed: a
        negative delta — the manager over-collected monthly and owes the difference back — is a
        legitimate outcome and is persisted as a negative `amount_cents`." And "The `FINAL` accrual
        it created is visible in that period's accrual list under `variant` `FINAL`"

        Design: Corner/endpoints/annual_true_up_returns_a_computed_projection
        """
        state = _true_up_projection_hotel(scenario)

        summary = scenario.true_up(state["agreement_id"], 2026)

        assert summary["annual_agop_cents"] == 20220000
        # Excess 8220000: 5000000 at 0.10 plus 3220000 at 0.15.
        assert summary["final_incentive_fee_cents"] == 983000
        assert summary["provisional_incentive_total_cents"] == 1922000
        assert summary["true_up_delta_cents"] == -939000
        rows = assert_page(
            scenario.api.list_fee_accruals(
                state["package_id"],
                ASSET_HEADERS,
                {"fee_type": FeeType.INCENTIVE, "variant": FeeVariant.FINAL},
            ),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )
        assert rows[0]["id"] == summary["true_up_accrual_id"]
        assert rows[0]["amount_cents"] == -939000
