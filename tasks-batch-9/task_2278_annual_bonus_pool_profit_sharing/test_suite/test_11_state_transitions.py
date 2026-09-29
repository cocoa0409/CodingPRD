"""Initial states, the transitions that are declared, and the ones that are not."""

from test_helpers import (
    CC_SCORECARD,
    FC,
    HR,
    HRBP_USER,
    HRBP_USER_ALT,
    PA,
    PAYMENT_DATE_CLOCK,
    ApiErrorId,
    BonusPlanScenario,
    accrual_period_payload,
    assert_pct,
    build_allocated_scenario,
    build_locked_scenario,
    build_settled_scenario,
    dispute_resolution_payload,
    make_hr_headers,
    metric_actual_payload,
    payout_run_payload,
    submit_scorecard_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _metric_only_scenario(plan_name: str) -> BonusPlanScenario:
    """One plan carrying a single REVENUE metric, band 900/1000/1200, still DRAFT."""
    scenario = BonusPlanScenario()
    scenario.create_plan(plan_name=plan_name, discretionary_budget_pct=10.00)
    scenario.add_metric(
        "REVENUE",
        weight_pct=100.00,
        threshold_value=900,
        target_value=1000,
        max_value=1200,
    )
    return scenario


class TestCompanyMetricActualTransition:
    def test_the_first_actual_moves_the_metric_and_scores_the_hard_cap(self, api):
        """PRD §3.4: "The audited outcome of a company metric arrives as a single filing
        by a `PlanAdmin`, which carries `actual_value` and an optional `source_note`
        recording provenance and moves the metric from `DRAFT` to `ACTUAL_ENTERED`." And
        PRD §3.4: "An actual at or above `max_value` scores exactly 150.00, the hard cap."

        Design: Corner/state_machines/metric_moves_to_actual_entered_on_the_first_actual
        """
        scenario = _metric_only_scenario("FY26 Metric Transition Plan")
        assert scenario.metrics["REVENUE"]["status"] == "DRAFT"

        filed = scenario.file_actual("REVENUE", 1200, source_note="blow-out year")

        assert filed["status"] == "ACTUAL_ENTERED"
        assert_pct(filed["achievement_pct"], 150.00)
        assert filed["actual_value"] == 1200

        _, meta = validate_paginated(
            api.list_company_metrics(
                PA, params={"plan_id": scenario.plan_id, "status": "ACTUAL_ENTERED"}
            )
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_company_metrics(
                PA, params={"plan_id": scenario.plan_id, "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 0

    def test_a_second_actual_is_refused_and_does_not_re_base_the_first(self, api):
        """PRD §3.4: "It may be filed exactly once — a second filing against a metric
        already in `ACTUAL_ENTERED` is `ERR_METRIC_ACTUAL_ALREADY_FILED` — and only while
        the plan is still in setup."

        Design: Corner/state_machines/second_metric_actual_rejected_as_already_filed
        """
        scenario = _metric_only_scenario("FY26 Metric Idempotency Plan")
        scenario.file_actual("REVENUE", 1000, source_note="audited")
        metric_id = scenario.metrics["REVENUE"]["id"]

        response = api.file_metric_actual(
            metric_id,
            metric_actual_payload(1100, source_note="second attempt"),
            PA,
        )
        validate_error(
            response,
            ApiErrorId.ERR_METRIC_ACTUAL_ALREADY_FILED.value,
            expected_status=409,
        )

        stored = validate_success(api.get_company_metric(metric_id, PA))
        assert stored["actual_value"] == 1000
        assert_pct(stored["achievement_pct"], 100.00)
        assert stored["source_note"] == "audited"
        assert stored["status"] == "ACTUAL_ENTERED"


class TestTransitionsThatAreNotDeclared:
    def test_submitting_a_draft_plan_for_certification_is_a_state_error(self, api):
        """PRD §2.10: "**Lifecycle state**, in this order: the plan being in the state its
        own requested transition needs (`ERR_PLAN_STATE_INVALID`), setup-phase writes
        needing a plan in `DRAFT` or `TARGETS_SET` (`ERR_PLAN_NOT_IN_SETUP`),
        allocation-phase writes needing the allocation states
        (`ERR_PLAN_NOT_IN_ALLOCATION`), a metric actual not already filed
        (`ERR_METRIC_ACTUAL_ALREADY_FILED`), the pool being in the state its requested
        transition needs (`ERR_POOL_STATE_INVALID`), the pool being open for money
        movement (`ERR_POOL_NOT_ALLOCATING`), the award's allocation state permitting the
        operation (`ERR_AWARD_STATE_INVALID`), the adjustment's state permitting a decision
        or a reversal (`ERR_ADJUSTMENT_NOT_PENDING`), the accrual period's state permitting
        a post or a reverse (`ERR_ACCRUAL_ALREADY_POSTED`), the plan not having reached
        settlement when accruing (`ERR_PLAN_ALREADY_SETTLED`), the payout run's state
        permitting execution or settlement and only one run existing per plan
        (`ERR_PAYOUT_ALREADY_EXECUTED`), the plan being locked to execute and paid out to
        settle (`ERR_PLAN_NOT_LOCKED`), the dispute's state permitting assignment or
        resolution (`ERR_DISPUTE_NOT_UNDER_REVIEW`), and a dispute being filed only in the
        permitted plan states (`ERR_DISPUTE_NOT_ALLOWED_YET`)."

        Design: Corner/state_machines/submit_for_certification_from_draft_rejected
        """
        scenario = BonusPlanScenario()
        scenario.create_plan(
            plan_name="FY26 Invalid From Plan", discretionary_budget_pct=10.00
        )

        response = api.submit_plan_for_certification(scenario.plan_id, PA)
        error = validate_error(
            response, ApiErrorId.ERR_PLAN_STATE_INVALID.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_METRIC_WEIGHTS_INVALID.value
        assert error["error_id"] != ApiErrorId.ERR_NO_ELIGIBLE_PARTICIPANTS.value

        plan = scenario.refresh_plan()
        assert plan["status"] == "DRAFT"
        assert plan["version"] == 1

    def test_submitting_calibration_from_an_already_submitted_pool_is_a_pool_state_error(
        self, api
    ):
        """PRD §3.7: "Submitting from any state other than `FUNDED` or `ALLOCATING` is
        `ERR_POOL_STATE_INVALID`."

        The plan is deliberately left in `ALLOCATION_OPEN` so the pool-state check is
        the earliest ladder position this request violates: PRD §2.10 orders
        "allocation-phase writes needing the allocation states
        (`ERR_PLAN_NOT_IN_ALLOCATION`)" *before* "the pool being in the state its
        requested transition needs (`ERR_POOL_STATE_INVALID`)", so a plan outside
        `ALLOCATION_OPEN` would legitimately mask this error.

        Design: Corner/state_machines/submit_calibration_from_a_draft_pool_rejected
        """
        scenario = build_allocated_scenario(
            units=("UNIT-B6",),
            plan_overrides={"plan_name": "FY26 Pool Precondition Plan"},
        )
        scenario.submit_calibration("UNIT-B6")
        assert scenario.pools["UNIT-B6"]["calibration_status"] == "CALIBRATION_SUBMITTED"

        response = api.submit_calibration(
            scenario.pool_id("UNIT-B6"), scenario.manager_headers("UNIT-B6")
        )
        error = validate_error(
            response, ApiErrorId.ERR_POOL_STATE_INVALID.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_PLAN_NOT_IN_ALLOCATION.value

        pool = scenario.refresh_pool("UNIT-B6")
        assert pool["calibration_status"] == "CALIBRATION_SUBMITTED"
        assert scenario.refresh_plan()["status"] == "ALLOCATION_OPEN"


class TestDeclaredInitialStates:
    def test_the_whole_chain_starts_in_the_states_the_contract_declares(self, api):
        """PRD §3.3: "A newly created award starts with `allocation_status` `UNALLOCATED`
        and `payment_status` `PENDING`, with `proposed_allocation_cents` 0,
        `allocation_ratio` 0.0000, `adjustment_total_cents` 0, `final_award_cents` 0,
        `payout_amount_cents` 0, `retraction_count` 0 and an empty `allocation_rationale`."
        And PRD §3.8: "A new period starts with `status` `OPEN`."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
        """
        scenario = BonusPlanScenario()
        scenario.add_unit("UNIT-B1", name="Unit B1")
        scenario.create_plan(
            plan_name="FY26 Initial State Plan", discretionary_budget_pct=10.00
        )
        scenario.add_target("L5", target_bonus_pct=20.00)
        scenario.add_metric(
            "REVENUE",
            weight_pct=100.00,
            threshold_value=900,
            target_value=1000,
            max_value=1200,
        )
        scenario.add_pool("UNIT-B1")
        scenario.add_participant(
            "ini",
            "UNIT-B1",
            employee_code="E601",
            full_name="Ini Tial",
            job_level="L5",
            base_salary_cents=20000000,
            hire_date="2025-03-01",
        )
        period = scenario.open_accrual_period("2026-01-01", "2026-06-30", 100.00)
        assert scenario.plan["status"] == "DRAFT"

        scenario.assign_targets()

        assert scenario.plan["status"] == "TARGETS_SET"
        assert (
            validate_success(api.get_company_metric(scenario.metrics["REVENUE"]["id"], PA))[
                "status"
            ]
            == "DRAFT"
        )
        assert scenario.refresh_pool("UNIT-B1")["calibration_status"] == "DRAFT"
        assert validate_success(api.get_accrual_period(period["id"], FC))["status"] == "OPEN"

        award = scenario.refresh_award("ini")
        assert award["allocation_status"] == "UNALLOCATED"
        assert award["payment_status"] == "PENDING"
        assert award["eligibility_status"] == "ELIGIBLE"
        assert award["prorated_target_cents"] == 4000000
        assert award["proposed_allocation_cents"] == 0
        assert award["retraction_count"] == 0


class TestScorecardReturnReopensThePool:
    def test_a_returned_scorecard_goes_back_to_draft_and_accepts_a_revision(self, api):
        """PRD §3.4: "`RETURN` moves the pool from `SCORECARD_SUBMITTED` back to `DRAFT`
        and clears `scorecard_certified_by_user_id`, so the unit revises and resubmits; a
        pool may travel `DRAFT` to `SCORECARD_SUBMITTED` to `DRAFT` as often as the
        committee insists."

        Design: Corner/state_machines/scorecard_return_sends_the_pool_back_to_draft_and_clears_the_certifier
        """
        scenario = BonusPlanScenario()
        scenario.add_unit("UNIT-B3", name="Unit B3")
        scenario.create_plan(
            plan_name="FY26 Scorecard Return Plan", discretionary_budget_pct=10.00
        )
        scenario.add_target("L5", target_bonus_pct=20.00)
        scenario.add_pool("UNIT-B3")
        scenario.submit_scorecard(
            "UNIT-B3", 140.00, scorecard_narrative="best year ever"
        )

        returned = scenario.decide_scorecard(
            "UNIT-B3",
            "RETURN",
            user_id=CC_SCORECARD,
            decision_note="evidence does not support 140.00",
        )
        assert returned["calibration_status"] == "DRAFT"
        assert returned["scorecard_certified_by_user_id"] is None

        revised = validate_success(
            api.submit_scorecard(
                scenario.pool_id("UNIT-B3"),
                submit_scorecard_payload(
                    92.50,
                    scorecard_narrative="restated against audited unit results",
                ),
                scenario.manager_headers("UNIT-B3"),
            )
        )
        assert revised["calibration_status"] == "SCORECARD_SUBMITTED"
        assert_pct(revised["bu_metric_achievement_pct"], 92.50)
        assert revised["scorecard_narrative"] == "restated against audited unit results"
        assert revised["funded_cents"] == 0
        assert revised["distribution_status"] == "NO_ELIGIBLE_PARTICIPANTS"


def _executed_with_live_dispute(plan_name: str, claimed_amount_cents: int, reason: str):
    """A locked plan whose only award is executed while a dispute is under review."""
    scenario = build_locked_scenario(
        units=("UNIT-B4",), plan_overrides={"plan_name": plan_name}
    )
    dispute = scenario.file_dispute(
        "ada", dispute_reason=reason, claimed_amount_cents=claimed_amount_cents
    )
    scenario.set_clock(PAYMENT_DATE_CLOCK)
    scenario.open_payout_run(run_note="FY26 payout")
    scenario.execute_payout()
    scenario.assign_dispute_review(
        dispute["id"], reviewer_note="reviewing the calibration record"
    )
    return scenario, dispute["id"]


class TestDisputeResolutionDrivesThePaymentAxis:
    def test_an_adjusted_resolution_overrides_the_payout_and_not_the_award(self, api):
        """PRD §3.10: "On success the award's `payout_amount_cents` becomes
        `adjusted_amount_cents` and its `payment_status` becomes `PAID`, the plan's
        `dispute_adjustment_cents` accumulates the signed difference between
        `adjusted_amount_cents` and the award's `final_award_cents`, and the plan's
        `paid_total_cents` is recomputed."

        Design: Corner/state_machines/dispute_resolution_adjust_overrides_the_payout_amount
        """
        scenario, dispute_id = _executed_with_live_dispute(
            "FY26 Dispute Adjust Plan", 5200000, "my calibration score was mis-keyed"
        )
        assert scenario.refresh_award("ada")["payout_amount_cents"] == 4000000

        dispute = validate_success(
            api.resolve_dispute(
                dispute_id,
                dispute_resolution_payload(
                    "ADJUST",
                    adjusted_amount_cents=5000000,
                    resolution_note="partially upheld; award raised to 5,000,000",
                ),
                make_hr_headers(HRBP_USER_ALT),
            )
        )

        assert dispute["status"] == "RESOLVED_ADJUSTED"
        assert dispute["resolution"] == "ADJUST"
        assert dispute["adjusted_amount_cents"] == 5000000
        assert dispute["resolved_by_user_id"] == HRBP_USER_ALT
        assert dispute["assigned_by_user_id"] == HRBP_USER

        award = scenario.refresh_award("ada")
        assert award["payment_status"] == "PAID"
        assert award["payout_amount_cents"] == 5000000
        assert award["final_award_cents"] == 4000000
        assert award["allocation_status"] == "LOCKED"

        plan = scenario.refresh_plan()
        assert plan["paid_total_cents"] == 5000000
        assert plan["dispute_adjustment_cents"] == 1000000
        assert plan["status"] == "PAID_OUT"

    def test_a_resolved_dispute_refuses_a_second_verdict(self, api):
        """PRD §3.10: "Taking a dispute that is not `OPEN` under review, or resolving one
        that is not `UNDER_REVIEW`, is refused with `ERR_DISPUTE_NOT_UNDER_REVIEW`."

        Design: Corner/state_machines/resolved_dispute_rejects_a_second_resolve
        """
        scenario, dispute_id = _executed_with_live_dispute(
            "FY26 Dispute Terminal Plan", 4000000, "process complaint"
        )
        upheld = validate_success(
            api.resolve_dispute(
                dispute_id,
                dispute_resolution_payload(
                    "UPHOLD", resolution_note="original award stands"
                ),
                make_hr_headers(HRBP_USER_ALT),
            )
        )
        assert upheld["status"] == "RESOLVED_UPHELD"

        # A third partner tries the same dispute again.
        response = api.resolve_dispute(
            dispute_id,
            dispute_resolution_payload(
                "ADJUST",
                adjusted_amount_cents=6000000,
                resolution_note="second bite at the apple",
            ),
            make_hr_headers("hrbp_3"),
        )
        validate_error(
            response, ApiErrorId.ERR_DISPUTE_NOT_UNDER_REVIEW.value, expected_status=409
        )

        stored = validate_success(api.get_dispute(dispute_id, HR))
        assert stored["status"] == "RESOLVED_UPHELD"
        assert stored["resolution"] == "UPHOLD"
        assert stored["adjusted_amount_cents"] is None
        assert stored["resolved_by_user_id"] == HRBP_USER_ALT

        award = scenario.refresh_award("ada")
        assert award["payment_status"] == "PAID"
        assert award["payout_amount_cents"] == 4000000
        assert scenario.refresh_plan()["dispute_adjustment_cents"] == 0


class TestSettledPlanIsTerminal:
    def test_neither_a_new_accrual_period_nor_a_second_run_survives_settlement(
        self, api
    ):
        """PRD §3.8: "A period may not be opened or posted once the plan has reached
        `PAID_OUT` or `SETTLED`, and may not be reversed once the plan has reached
        `SETTLED` — reversal is still permitted while the plan is `PAID_OUT` — with either
        refusal reported as `ERR_PLAN_ALREADY_SETTLED`." And PRD §3.9: "At most one run may
        exist per plan; a second attempt is refused with `ERR_PAYOUT_ALREADY_EXECUTED`, as
        is executing a run that is not in `DRAFT` or settling one that is not in
        `EXECUTED`."

        Design: Corner/state_machines/settled_plan_rejects_further_accrual_and_payout_writes
        """
        scenario = build_settled_scenario(
            units=("UNIT-B2",),
            plan_overrides={"plan_name": "FY26 Terminal Lockdown Plan"},
        )

        accrual_attempt = api.create_accrual_period(
            accrual_period_payload(scenario.plan_id, "2026-01-01", "2026-06-30", 100.00),
            FC,
        )
        validate_error(
            accrual_attempt,
            ApiErrorId.ERR_PLAN_ALREADY_SETTLED.value,
            expected_status=409,
        )

        second_run = api.create_payout_run(
            payout_run_payload(scenario.plan_id, run_note="second run"), FC
        )
        validate_error(
            second_run,
            ApiErrorId.ERR_PAYOUT_ALREADY_EXECUTED.value,
            expected_status=409,
        )

        plan = scenario.refresh_plan()
        assert plan["status"] == "SETTLED"
        assert plan["paid_total_cents"] == 4000000
        assert plan["settlement_burden_cents"] == 306000
        assert plan["accrued_total_cents"] == 0
        assert plan["true_up_cents"] == 4306000

        run = validate_success(api.get_payout_run(scenario.payout_run["id"], FC))
        assert run["status"] == "SETTLED"
        assert run["paid_award_count"] == 1

        _, meta = validate_paginated(
            api.list_payout_runs(FC, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 1

        _, meta = validate_paginated(
            api.list_accrual_periods(FC, params={"plan_id": scenario.plan_id})
        )
        assert meta["total_count"] == 0
