"""Waterfall evaluation: step results, branch stack, offer/denial outcomes, OCC."""
import pytest

from test_helpers import (
    AGENT,
    OPS,
    UW,
    ApiErrorId,
    FIXTURE_A_DOCS,
    FIXTURE_A_LOAN,
    FIXTURE_A_STATED_INCOME,
    acknowledge,
    assert_step_result,
    board_loan,
    create_program_option_payload,
    create_std_mod_program,
    get_application,
    get_success_data,
    make_borrower,
    make_underwriter_headers,
    run_waterfall,
    setup_complete_application,
    setup_offered_plan,
    submit_and_accept_documents,
    submit_application,
    validate_error,
    validate_success,
)


class TestStepResults:
    def test_step_results_are_immutable_snapshot_rows(self, api):
        """PRD §2.4: "The `EvaluationStepResult` entity is the single exception:
        it carries only `id` and `created_at`, and has no `updated_at` or
        `version`; step results are immutable snapshots of a waterfall run."

        Design: Corner/entities/evaluation_step_result_immutable_event_rows
        """
        scenario = setup_offered_plan(economics="B")
        steps = get_success_data(
            api.list_evaluation_steps(scenario["evaluation"]["id"], UW)
        )
        assert len(steps) == 1
        assert_step_result(steps[0])
        step = steps[0]
        assert step["program_code"] == "STD_MOD"
        assert step["step_rank"] == 1
        assert step["eligible"] is True
        assert step["achieved_pi_cents"] == 100_000
        assert step["met_target"] is True
        assert step["selected"] is True


class TestBranchStack:
    def test_all_three_waterfall_branches_engage(self, api):
        """PRD §3.6: "3. **Rate reduction loop** — starting from the loan's
        `interest_rate_bp` and `remaining_term_months`, iteratively reduce the
        rate by `rate_step_bp` (each step clamped at `rate_floor_bp` via
        `max(rate_floor_bp, rate - rate_step_bp)`) while the rate remains above
        `rate_floor_bp` **and** the annuity payment at the current base, rate,
        and term exceeds the target. The loop stops at the floor."
        PRD §3.6: "4. **Term extension** — if the annuity at the post-rate-loop
        terms still exceeds the target, the term jumps in a single step to the
        program's `max_term_months`."
        PRD §3.6: "5. **Principal forbearance** — if the annuity still exceeds the
        target, compute the forbearance cap as the base multiplied by
        `max_forbearance_pct_bp` and divided by ten thousand, rounded half-up;
        compute the needed forbearance as the base minus the present value of the
        target payment at the current rate and term (the standard annuity
        discount), rounded half-up; the actual forbearance is the smaller of cap
        and needed."

        Design: Difficulty/combinatorial_formula/waterfall_rate_term_forbearance_branch_stack
        """
        scenario = setup_complete_application(economics="B")
        ev = run_waterfall(scenario["application"]["id"])
        assert ev["result"] == "OFFER"
        assert ev["eval_base_cents"] == 36_000_000
        assert ev["target_payment_cents"] == 100_000
        # Rate floor binds (600 -> 200), term jumps 240 -> 480, forbearance is
        # min(cap 10800000, needed) = 2977697.
        assert ev["offered_rate_bp"] == 200
        assert ev["offered_term_months"] == 480
        assert ev["offered_forbearance_cents"] == 2_977_697
        assert ev["offered_pi_cents"] == 100_000

    def test_branch_stack_step_row_records_achieved_payment(self, api):
        """PRD §3.6: "For each eligible program the waterfall computes the
        **provisional variant** of the modified-payment calculation, recording
        per-step `achieved_pi_cents`, a `met_target` flag (true when the achieved
        payment is at or below the target, eligible programs only), and a
        `selected` flag (true on exactly one step — the first eligible program
        that met target, where the waterfall stops)"
        PRD §3.6: "The waterfall stops at the first eligible program whose
        achieved payment meets the target — exactly one step is marked
        `selected: true`."

        Design: Difficulty/combinatorial_formula/waterfall_rate_term_forbearance_branch_stack
        """
        scenario = setup_complete_application(economics="B")
        ev = run_waterfall(scenario["application"]["id"])
        steps = get_success_data(api.list_evaluation_steps(ev["id"], UW))
        assert len(steps) == 1
        step = steps[0]
        assert step["program_code"] == "STD_MOD"
        assert step["eligible"] is True
        assert step["achieved_pi_cents"] == 100_000
        assert step["met_target"] is True
        assert step["selected"] is True


class TestTargetEqualityBoundary:
    def test_payment_equal_to_target_qualifies(self, api):
        """PRD §3.6: "The program qualifies when `achieved_pi_cents` is less than
        or equal to `target_payment_cents` — the boundary is inclusive, so a
        payment exactly equal to the target qualifies."

        Design: Difficulty/boundary_precision_check/target_ratio_equality_qualifies_for_offer
        """
        scenario = setup_complete_application(economics="B")
        ev = run_waterfall(scenario["application"]["id"])
        assert ev["target_payment_cents"] == 100_000
        assert ev["offered_pi_cents"] == 100_000
        assert ev["result"] == "OFFER"

    def test_equality_offer_creates_trial_plan(self, api):
        """PRD §3.6: "**OFFER** — `result` is `OFFER`, `selected_program_id` is
        set, and the offered terms are frozen onto the evaluation as
        `offered_rate_bp`, `offered_term_months`, `offered_forbearance_cents`,
        and `offered_pi_cents`. A `TrialPaymentPlan` is created in `OFFERED` with
        three `SCHEDULED` `TrialPayment`s (see §3.7), and the application
        transitions from `COMPLETE_PACKAGE` to `EVALUATED_OFFER`."

        Design: Difficulty/boundary_precision_check/target_ratio_equality_qualifies_for_offer
        """
        scenario = setup_offered_plan(economics="B")
        assert scenario["evaluation"]["result"] == "OFFER"
        assert scenario["evaluation"]["selected_program_id"] == scenario["program"]["id"]
        assert scenario["application"]["status"] == "EVALUATED_OFFER"
        plan = scenario["plan"]
        assert plan["status"] == "OFFERED"
        assert plan["periods"] == 3
        payments = scenario["payments"]
        assert len(payments) == 3
        assert all(p["status"] == "SCHEDULED" for p in payments)


class TestWaterfallOrdering:
    def test_waterfall_stops_at_first_success_in_rank_order(self, api, admin_headers):
        """PRD §3.6: "The waterfall walks `ACTIVE` programs in ascending
        `waterfall_rank` (ties broken by `created_at` ascending)."
        PRD §3.6: "The waterfall stops at the first eligible program whose
        achieved payment meets the target — exactly one step is marked
        `selected: true`. Programs after the stop are never evaluated and produce
        no step rows."

        Design: Corner/calculations/waterfall_stops_at_first_success_in_rank_order
        """
        borrower = make_borrower(full_name="Ursula U", email="ursula@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-CALC3", **FIXTURE_A_LOAN)
        std = get_success_data(api.create_program_option(
            create_program_option_payload(), admin_headers))
        get_success_data(api.create_program_option(
            create_program_option_payload(
                code="FLEX_MOD", waterfall_rank=2, target_dti_bp=2500,
                rate_floor_bp=300, max_term_months=360,
                max_forbearance_pct_bp=2000,
            ), admin_headers))
        app = submit_application(
            loan, borrower["id"], stated_income=FIXTURE_A_STATED_INCOME
        )
        acknowledge(app["id"])
        submit_and_accept_documents(app["id"], borrower["id"], FIXTURE_A_DOCS)

        ev = run_waterfall(app["id"])
        assert ev["result"] == "OFFER"
        assert ev["selected_program_id"] == std["id"]
        assert ev["offered_pi_cents"] == 148_842
        steps = get_success_data(api.list_evaluation_steps(ev["id"], UW))
        assert len(steps) == 1, "FLEX_MOD (rank 2) must never be evaluated"
        assert steps[0]["program_code"] == "STD_MOD"
        assert steps[0]["selected"] is True


class TestWaterfallDenials:
    def test_denial_no_eligible_program(self, api):
        """PRD §3.6: "`NO_ELIGIBLE_PROGRAM` when no program's eligibility band
        admitted the loan"
        PRD §3.6: "the loan's `delinquency_days` must fall within the program's
        `min_delinquency_days`–`max_delinquency_days` window, both bounds
        inclusive."
        PRD §3.6: "**DENIAL** — `result` is `DENIAL`, `selected_program_id` is
        null, and `denial_reasons` is a non-empty subset of
        {`NO_ELIGIBLE_PROGRAM`, `TARGET_NOT_ACHIEVABLE`, `INCOME_UNVERIFIABLE`}"

        Design: Corner/calculations/waterfall_denial_no_eligible_program
        """
        # Delinquency 30 is outside STD_MOD's inclusive [61, 720] band.
        scenario = setup_complete_application(
            economics="A", loan_overrides={"delinquency_days": 30},
        )
        ev = run_waterfall(scenario["application"]["id"])
        assert ev["result"] == "DENIAL"
        assert ev["selected_program_id"] is None
        assert ev["denial_reasons"] == ["NO_ELIGIBLE_PROGRAM"]
        # PRD §3.6: "Ineligible programs still produce an `EvaluationStepResult`
        # recording `program_code`, `step_rank` (the snapshot of `waterfall_rank`
        # at evaluation time), and `eligible: false`".
        steps = get_success_data(api.list_evaluation_steps(ev["id"], UW))
        assert len(steps) == 1
        assert steps[0]["eligible"] is False
        assert steps[0]["selected"] is False
        notices = get_success_data(
            api.list_application_denial_notices(scenario["application"]["id"], UW)
        )
        assert len(notices) == 1
        assert notices[0]["reasons"] == ["NO_ELIGIBLE_PROGRAM"]
        assert notices[0]["status"] == "ISSUED"

    def test_denial_target_not_achievable_cap_bound(self, api):
        """PRD §3.6: "`TARGET_NOT_ACHIEVABLE` when at least one eligible program
        failed to reach the target"
        PRD §3.6: "the actual forbearance is the smaller of cap and needed."

        Design: Corner/calculations/waterfall_denial_target_not_achievable_cap_bound
        """
        # Fixture C economics: verified income 100000 -> target 31000; even
        # floor rate + max term + capped forbearance cannot reach it.
        scenario = setup_complete_application(economics="C")
        ev = run_waterfall(scenario["application"]["id"])
        assert ev["result"] == "DENIAL"
        assert ev["denial_reasons"] == ["TARGET_NOT_ACHIEVABLE"]
        steps = get_success_data(api.list_evaluation_steps(ev["id"], UW))
        assert len(steps) == 1
        step = steps[0]
        assert step["eligible"] is True
        assert step["achieved_pi_cents"] == 76_312
        assert step["met_target"] is False
        assert step["selected"] is False


class TestEvaluationPreconditions:
    def test_evaluation_requires_complete_package(self, api):
        """PRD §3.6: "Running an evaluation against an application that is not
        `COMPLETE_PACKAGE` is rejected with `ERR_APPLICATION_NOT_COMPLETE`."

        Design: Corner/errors/error_application_not_complete_on_early_evaluation
        """
        borrower = make_borrower(full_name="Will W", email="will@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-ERR1", delinquency_days=150)
        create_std_mod_program()
        app = submit_application(
            loan, borrower["id"], hardship_type="OTHER", stated_income=100_000
        )
        acknowledge(app["id"])
        current = get_application(app["id"])
        res = api.run_evaluation(
            app["id"],
            {"expected_application_version": current["version"]},
            UW,
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_COMPLETE, expected_status=409)
        evals = get_success_data(api.list_application_evaluations(app["id"], UW))
        assert evals == []

    def test_agent_cannot_run_evaluation(self, api, agent_headers):
        """PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /applications/{id}/evaluations — "Underwriter".

        Design: Corner/rbac/loss_mit_agent_cannot_run_evaluation
        """
        scenario = setup_complete_application(economics="A")
        app = scenario["application"]
        res = api.run_evaluation(
            app["id"],
            {"expected_application_version": app["version"]},
            agent_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_application(app["id"])["status"] == "COMPLETE_PACKAGE"

    def test_stale_application_version_rejected(self, api):
        """PRD §2.5: "Running a waterfall evaluation against an application
        requires `expected_application_version`, matched against the
        application's current `version`. A mismatch is rejected with
        `ERR_STALE_APPLICATION_VERSION` (HTTP 412)."
        PRD §2.7: "a stale `expected_loan_version` is reported before any
        state-machine error on the same request."

        Design: Corner/complexity_layers/occ_stale_application_version_on_evaluation_rerun
        """
        scenario = setup_offered_plan(economics="A")
        app = scenario["application"]
        stale_version = app["version"] - 1  # evaluation already bumped it
        res = api.run_evaluation(
            app["id"],
            {"expected_application_version": stale_version},
            UW,
        )
        validate_error(res, ApiErrorId.ERR_STALE_APPLICATION_VERSION, expected_status=412)
        evals = get_success_data(api.list_application_evaluations(app["id"], UW))
        assert len(evals) == 1
        assert get_success_data(api.get_evaluation(evals[0]["id"], UW))["status"] == "ACTIVE"
