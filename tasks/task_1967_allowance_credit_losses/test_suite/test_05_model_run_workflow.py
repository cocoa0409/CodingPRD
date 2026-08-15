"""Quarterly model run workflow: creation gates, review cycle, approval (PRD §2.5–§2.9, §3.6)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_model_run,
    create_draft_run,
    create_model_run_payload,
    executed_individual_run,
    execute_run,
    finalize_run,
    get_run,
    get_single_evaluation,
    make_chief_credit_officer_headers,
    make_credit_analyst_headers,
    patch_evaluation,
    prime_loan_spec,
    review_evaluation,
    setup_executed_run,
    setup_finalized_run,
    setup_run_environment,
    setup_under_review_run,
    submit_evaluation,
    submit_run_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRunCreationGates:
    def test_weight_sum_9999_rejected(self, api, credit_analyst_headers):
        """PRD §3.6: "A `CreditAnalyst` opens one by naming the `as_of_period` being estimated, the `loss_model_id` of the model to drive it, and the `scenario_weights` — a list of entries, each pairing a `scenario_id` with a positive integer `weight_bps`, where the weights must sum to exactly ten thousand basis points. A list whose weights sum to anything else, or that contains a non-positive weight, is rejected with `ERR_WEIGHT_SUM_INVALID` (HTTP 422); the accepted weights are pinned at creation and do not drift thereafter."

        Design: Difficulty/boundary_precision_check/weight_sum_exact_10000
        """
        env = setup_run_environment(loan_specs=[])
        res = api.create_model_run(
            create_model_run_payload(
                env.model["id"],
                [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 9_999}],
            ),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_WEIGHT_SUM_INVALID, 422)

    def test_weight_sum_10000_accepted(self, api, credit_analyst_headers):
        """PRD §3.6: "A `CreditAnalyst` opens one by naming the `as_of_period` being estimated, the `loss_model_id` of the model to drive it, and the `scenario_weights` — a list of entries, each pairing a `scenario_id` with a positive integer `weight_bps`, where the weights must sum to exactly ten thousand basis points."

        Design: Difficulty/boundary_precision_check/weight_sum_exact_10000
        """
        env = setup_run_environment(loan_specs=[])
        res = api.create_model_run(
            create_model_run_payload(
                env.model["id"],
                [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 10_000}],
                as_of_period="2026-Q2",
            ),
            credit_analyst_headers,
        )
        data = validate_success(res, 201)
        assert_model_run(data)
        assert data["status"] == "DRAFT"

    def test_run_create_invalid_period_format(self, api, credit_analyst_headers):
        """PRD §2.5: "Any period string in the API — an `as_of_period`, an `effective_from_period`, an `effective_to_period`, a `backtest_period`, a `charge_off_period`, or a `recovery_period` — must match the format `YYYY-Qn` with the quarter number n between 1 and 4; a malformed period string is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/run_create_invalid_period_format
        """
        env = setup_run_environment(loan_specs=[])
        res = api.create_model_run(
            create_model_run_payload(
                env.model["id"],
                [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 10_000}],
                as_of_period="2026-Q5",
            ),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_stale_period_and_archived_scenario_yields_period_error(self, api, credit_analyst_headers, model_validator_headers):
        """PRD §2.9: "Every request is checked against the same ordered ladder of validations, and when a request fails several rungs at once, the response always carries the error of the earliest rung it fails."
        PRD §2.9: "8. Period-forward discipline: a new model run's period must be strictly later than every finalized run's period, else `ERR_PERIOD_NOT_FORWARD`.
        9. Referenced configuration usability: the referenced loss model is active, the referenced segment is open, and every referenced scenario is active, else the corresponding `ERR_MODEL_NOT_ACTIVE`, `ERR_SEGMENT_NOT_OPEN`, or `ERR_SCENARIO_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_run_create
        """
        env = setup_finalized_run()  # FINALIZED run at 2026-Q1
        scenario = env.scenarios[0]
        # FINALIZED runs never block archiving, so this archive succeeds.
        validate_success(api.archive_economic_scenario(scenario["id"], model_validator_headers), 200)

        res = api.create_model_run(
            create_model_run_payload(
                env.model["id"],
                [{"scenario_id": scenario["id"], "weight_bps": 10_000}],
                as_of_period="2026-Q1",  # not strictly later than the FINALIZED run
            ),
            credit_analyst_headers,
        )
        # Temporal (rung 8) precedes referential (rung 9): the archived scenario
        # must not surface ERR_SCENARIO_NOT_ACTIVE here.
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_FORWARD, 409)

    def test_finalized_run_does_not_block_scenario_archive(self, api, model_validator_headers):
        """PRD §3.4: "A `FINALIZED` run's references are settled history and never block archiving."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_run_create
        """
        env = setup_finalized_run()
        scenario = env.scenarios[0]
        data = validate_success(
            api.archive_economic_scenario(scenario["id"], model_validator_headers), 200
        )
        assert data["status"] == "ARCHIVED"
        reread = validate_success(
            api.get_economic_scenario(scenario["id"], model_validator_headers), 200
        )
        assert reread["status"] == "ARCHIVED"


class TestRunLifecycle:
    def test_model_runs_list_pagination(self, api, credit_analyst_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Every list endpoint returns its resources sorted by creation timestamp in ascending order, and the `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/model_runs_list_pagination
        """
        env = setup_run_environment(loan_specs=[])
        run_2 = create_draft_run(
            env.model["id"],
            [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 10_000}],
            as_of_period="2026-Q2",
        )

        page1, meta1 = validate_paginated(
            api.list_model_runs(credit_analyst_headers, params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == env.run["id"]  # creation order ascending

        page2, meta2 = validate_paginated(
            api.list_model_runs(credit_analyst_headers, params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["id"] == run_2["id"]

    def test_execute_not_found_beats_state(self, api, credit_analyst_headers):
        """PRD §2.9: "Path existence: every identifier in the request path is resolved against existing resources in left-to-right order, and the first identifier that does not resolve rejects the whole request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier — or any body rule — is examined."

        Design: Corner/validations/execute_not_found_beats_state
        """
        res = api.execute_model_run(NON_EXISTENT_UUID, credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_version_increments_on_each_mutation(self, api, credit_analyst_headers):
        """PRD §2.4: "The `version` is a system-managed integer that increments by one on every mutation of the resource and anchors the optimistic concurrency checks described in §2.7."
        PRD §3.6: "The driving model's `version_label` is pinned onto the run as `model_version_label`, the executor's header identity is recorded as `executed_by_user_id`, and the run's `version` increments."

        Design: Corner/cross_cutting_layers/version_increments_on_each_mutation
        """
        env = setup_run_environment()
        v_create = env.run["version"]
        assert isinstance(v_create, int)

        executed = execute_run(env.run["id"])
        assert executed["version"] == v_create + 1, (
            "execute must increment the run version by exactly one"
        )
        submitted = submit_run_for_review(env.run["id"])
        assert submitted["version"] == executed["version"] + 1, (
            "submit_for_review must increment the run version by exactly one"
        )


class TestReworkCycle:
    def test_request_rework_returns_run_to_executed(self, api, chief_credit_officer_headers):
        """PRD §3.6: "Alternatively, the chief credit officer sends the run back, `UNDER_REVIEW` → `EXECUTED`, with `rework_notes` stored on the run for the analysts; this rework cycle can repeat as often as needed, and each pass increments the version."

        Design: Difficulty/non_linear_state_machine/model_run_rework_cycle
        """
        env = setup_under_review_run()  # PASS-only portfolio -> zero evaluations
        res = api.request_model_run_rework(
            env.run["id"],
            {"rework_notes": "Revisit qualitative overlay for energy exposure"},
            chief_credit_officer_headers,
        )
        data = validate_success(res, 200)
        assert data["status"] == "EXECUTED"
        assert data["rework_notes"] == "Revisit qualitative overlay for energy exposure"

    def test_reworked_run_can_be_resubmitted(self, api, credit_analyst_headers, chief_credit_officer_headers):
        """PRD §3.6: "Alternatively, the chief credit officer sends the run back, `UNDER_REVIEW` → `EXECUTED`, with `rework_notes` stored on the run for the analysts; this rework cycle can repeat as often as needed, and each pass increments the version."
        PRD §3.6: "From `EXECUTED`, a `CreditAnalyst` submits the run for review, moving it `EXECUTED` → `UNDER_REVIEW`; every one of the run's individual evaluations must be `REVIEWED` at that point, else the submission is rejected with `ERR_EVALUATIONS_OUTSTANDING` (HTTP 409) — a run with zero evaluations satisfies this vacuously — and the run's `version` increments."

        Design: Difficulty/non_linear_state_machine/model_run_rework_cycle
        """
        env = setup_under_review_run()
        validate_success(api.request_model_run_rework(
            env.run["id"], {"rework_notes": "Revisit qualitative overlay for energy exposure"},
            chief_credit_officer_headers,
        ), 200)
        resubmitted = validate_success(
            api.submit_model_run_for_review(env.run["id"], credit_analyst_headers), 200
        )
        assert resubmitted["status"] == "UNDER_REVIEW"


class TestSubmitRequiresReviewedEvaluations:
    def test_submit_for_review_blocked_by_unreviewed_evaluation(self, api, credit_analyst_headers):
        """PRD §3.6: "From `EXECUTED`, a `CreditAnalyst` submits the run for review, moving it `EXECUTED` → `UNDER_REVIEW`; every one of the run's individual evaluations must be `REVIEWED` at that point, else the submission is rejected with `ERR_EVALUATIONS_OUTSTANDING` (HTTP 409) — a run with zero evaluations satisfies this vacuously — and the run's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_all_evaluations_reviewed
        """
        env = executed_individual_run()  # one DRAFT evaluation
        res = api.submit_model_run_for_review(env.run["id"], credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_EVALUATIONS_OUTSTANDING, 409)
        assert get_run(env.run["id"])["status"] == "EXECUTED"

    def test_submit_for_review_succeeds_after_all_reviewed(self, api, credit_analyst_headers):
        """PRD §3.6: "From `EXECUTED`, a `CreditAnalyst` submits the run for review, moving it `EXECUTED` → `UNDER_REVIEW`; every one of the run's individual evaluations must be `REVIEWED` at that point, else the submission is rejected with `ERR_EVALUATIONS_OUTSTANDING` (HTTP 409) — a run with zero evaluations satisfies this vacuously — and the run's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_all_evaluations_reviewed
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        patch_evaluation(
            evaluation["id"], evaluation["version"],
            analysis_notes="Collateral-based reserve; guarantor support excluded.",
        )
        submit_evaluation(evaluation["id"])
        review_evaluation(evaluation["id"])

        data = validate_success(
            api.submit_model_run_for_review(env.run["id"], credit_analyst_headers), 200
        )
        assert data["status"] == "UNDER_REVIEW"


class TestApprovalGates:
    def test_approve_from_executed_rejected_invalid_state(self, api, chief_credit_officer_headers):
        """PRD §3.6: "A `ChiefCreditOfficer` then approves it, `UNDER_REVIEW` → `APPROVED`, subject to the segregation-of-duties rule of §2.8; the approver is recorded as `approved_by_user_id` and the version increments."
        PRD §2.9: "State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."

        Design: Corner/state_machines/approve_from_executed_rejected_invalid_state
        """
        env = setup_executed_run(executor_user_id="analyst-1")
        res = api.approve_model_run(env.run["id"], chief_credit_officer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert get_run(env.run["id"])["status"] == "EXECUTED"

    def test_approve_executed_run_by_executor_returns_state_error(self, api):
        """PRD §2.9: "Every request is checked against the same ordered ladder of validations, and when a request fails several rungs at once, the response always carries the error of the earliest rung it fails."
        PRD §2.9: "5. State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."
        PRD §2.9: "7. Segregation of duties: the approver differs from the executor or creator, per §2.8, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_approve
        """
        env = setup_executed_run(executor_user_id="analyst-1")
        # Approve attempt on an EXECUTED run by the same operator who executed it:
        # both rung 5 (state) and rung 7 (segregation) fail; rung 5 wins.
        res = api.approve_model_run(
            env.run["id"], make_chief_credit_officer_headers("analyst-1")
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_run_state_unchanged_after_rejected_approve(self, api):
        """PRD §2.9: "5. State-transition legality: the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any transition attempted from a state other than its declared source state fails here."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_approve
        """
        env = setup_executed_run(executor_user_id="analyst-1")
        api.approve_model_run(env.run["id"], make_chief_credit_officer_headers("analyst-1"))
        run = get_run(env.run["id"])
        assert run["status"] == "EXECUTED"
        assert run.get("approved_by_user_id") is None

    def test_run_approve_same_user_rejected_sod(self, api):
        """PRD §2.8: "Executing a model run records the acting analyst as the run's `executed_by_user_id`; approving that run requires a different operator — if the approver's `X-User-ID` equals the recorded `executed_by_user_id`, the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and a successful approval records the approver as `approved_by_user_id`."

        Design: Corner/rbac/run_approve_same_user_rejected_sod
        """
        env = setup_under_review_run(executor_user_id="analyst-1")
        same_user = api.approve_model_run(
            env.run["id"], make_chief_credit_officer_headers("analyst-1")
        )
        validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        data = validate_success(api.approve_model_run(
            env.run["id"], make_chief_credit_officer_headers("cco-1")
        ), 200)
        assert data["status"] == "APPROVED"
        assert data["approved_by_user_id"] == "cco-1"

    def test_validator_cannot_approve_run(self, api, model_validator_headers):
        """PRD §2.1: "A `ChiefCreditOfficer` holds approval authority: qualitative factor approval and retirement, run approval, rework and finalization, evaluation review and reopen, and management adjustment decisions."
        PRD §2.1: "A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/validator_cannot_approve_run
        """
        env = setup_under_review_run()
        res = api.approve_model_run(env.run["id"], model_validator_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert get_run(env.run["id"])["status"] == "UNDER_REVIEW"
