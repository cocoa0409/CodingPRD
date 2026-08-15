"""Individual evaluations: dual-method reserves, review/reopen cycle, OCC (PRD §2.7, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_individual_evaluation,
    create_draft_run,
    executed_individual_run,
    execute_run,
    get_run,
    get_single_evaluation,
    list_run_evaluations,
    patch_evaluation,
    review_evaluation,
    setup_executed_run,
    setup_run_environment,
    submit_evaluation,
    substandard_loan_spec,
    validate_error,
    validate_paginated,
    validate_success,
)

DCF_FLOWS = [130_000, 130_000, 130_000, 130_000]


class TestSpecificReserveMethods:
    def test_collateral_fair_value_reserve_at_execute(self, api):
        """PRD §3.6: "One individual evaluation is created for every `ACTIVE` loan whose `individually_evaluated` flag is true — each starting in `DRAFT` with method `COLLATERAL_FAIR_VALUE` and its `collateral_value_cents` copied from the loan — and `individual_evaluation_count` records how many were created."
        PRD §3.7: "Under `COLLATERAL_FAIR_VALUE`, the reserve is driven by liquidation value: the net collateral is the evaluation's `collateral_value_cents` minus a cost-to-sell haircut, where the haircut is the collateral value multiplied by one thousand basis points — ten percent — divided by ten thousand and rounded half-up to whole cents; the `specific_reserve_cents` is then the loan's `amortized_cost_cents` minus that net collateral, floored at zero."

        Design: Difficulty/dual_variant_calc/collateral_vs_dcf_specific_reserve
        """
        env = setup_executed_run(
            segment_specs=[{"name": "SmallBiz Subprime", "product_type": "SMALL_BUSINESS",
                            "risk_rating_band": "SUBPRIME", "vintage_year": 2023}],
            loan_specs=[substandard_loan_spec(), substandard_loan_spec()],
        )
        assert env.run["individual_evaluation_count"] == 2
        for loan in env.loans:
            evaluation = get_single_evaluation(env.run["id"], loan_id=loan["id"])
            assert evaluation["method"] == "COLLATERAL_FAIR_VALUE"
            assert evaluation["collateral_value_cents"] == 460_000
            # haircut = round_half_up(460000 * 1000 / 10000) = 46000;
            # reserve = 500000 - (460000 - 46000) = 86000
            assert evaluation["specific_reserve_cents"] == 86_000

    def test_discounted_cash_flow_reserve_after_patch(self, api):
        """PRD §3.7: "Under `DISCOUNTED_CASH_FLOW`, the reserve is driven by the present value of expected collections: the quarterly discount rate is the `discount_rate_bps` divided by ten thousand, and the present value is the sum, over each quarter t from one to the number of entries in `expected_quarterly_cash_flows_cents`, of that quarter's expected cash flow divided by one plus the quarterly rate raised to the power t; this sum is computed exactly and rounded half-up to whole cents once at the end, and the `specific_reserve_cents` is the loan's `amortized_cost_cents` minus that rounded present value, floored at zero."
        PRD §3.7: "Identical loan data under the two methods yields different reserves; that divergence is intentional and is why the method choice is a documented judgment."

        Design: Difficulty/dual_variant_calc/collateral_vs_dcf_specific_reserve
        """
        env = setup_executed_run(
            segment_specs=[{"name": "SmallBiz Subprime", "product_type": "SMALL_BUSINESS",
                            "risk_rating_band": "SUBPRIME", "vintage_year": 2023}],
            loan_specs=[substandard_loan_spec(), substandard_loan_spec()],
        )
        eval_b = get_single_evaluation(env.run["id"], loan_id=env.loans[1]["id"])
        patched = patch_evaluation(
            eval_b["id"], eval_b["version"],
            method="DISCOUNTED_CASH_FLOW",
            expected_quarterly_cash_flows_cents=DCF_FLOWS,
            discount_rate_bps=300,
        )
        assert patched["method"] == "DISCOUNTED_CASH_FLOW"
        # PV of 4 x 130000 at 3% per quarter = 483223; reserve = 500000 - 483223
        assert patched["specific_reserve_cents"] == 16_777

        eval_a = get_single_evaluation(env.run["id"], loan_id=env.loans[0]["id"])
        assert eval_a["specific_reserve_cents"] == 86_000
        assert eval_a["specific_reserve_cents"] != patched["specific_reserve_cents"]


class TestEvaluationWorkflow:
    def test_evaluation_submit_without_notes_rejected(self, api, credit_analyst_headers):
        """PRD §3.7: "Submission by a `CreditAnalyst` additionally requires the `analysis_notes` to be non-empty after trimming, else `ERR_ANALYSIS_DOCUMENTATION_REQUIRED` (HTTP 422); a successful submission re-syncs the run's individual reserve and total allowance."

        Design: Corner/state_machines/evaluation_submit_without_notes_rejected
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        res = api.submit_individual_evaluation(evaluation["id"], credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_ANALYSIS_DOCUMENTATION_REQUIRED, 422)
        reread = validate_success(
            api.get_individual_evaluation(evaluation["id"], credit_analyst_headers), 200
        )
        assert reread["status"] == "DRAFT"

    def test_reopen_returns_evaluation_to_submitted(self, api, chief_credit_officer_headers):
        """PRD §3.7: "The evaluation's own workflow runs `DRAFT` → `SUBMITTED` → `REVIEWED`, with a reopen cycle back from `REVIEWED` to `SUBMITTED`, and every step is gated on the parent run still being workable — `EXECUTED` or `UNDER_REVIEW`; once the run has moved on, evaluation changes are rejected with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.7: "Reopening, also by a `ChiefCreditOfficer` and carrying a `reopen_reason`, returns the evaluation to `SUBMITTED` and recomputes the reviewed count, so the count always reflects the live set."

        Design: Difficulty/non_linear_state_machine/evaluation_reopen_cycle
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        patch_evaluation(evaluation["id"], evaluation["version"],
                         analysis_notes="Borrower downgraded after covenant breach; collateral-based reserve appropriate.")
        submit_evaluation(evaluation["id"])
        review_evaluation(evaluation["id"])
        assert get_run(env.run["id"])["reviewed_evaluation_count"] == 1

        data = validate_success(api.reopen_individual_evaluation(
            evaluation["id"], {"reopen_reason": "Re-verify collateral appraisal date"},
            chief_credit_officer_headers,
        ), 200)
        assert data["status"] == "SUBMITTED"
        assert get_run(env.run["id"])["reviewed_evaluation_count"] == 0

    def test_second_review_restores_reviewed_count(self, api, chief_credit_officer_headers):
        """PRD §3.7: "Review by a `ChiefCreditOfficer` recomputes the run's `reviewed_evaluation_count` — the number of the run's evaluations currently in `REVIEWED` — and re-syncs the same run totals. Reopening, also by a `ChiefCreditOfficer` and carrying a `reopen_reason`, returns the evaluation to `SUBMITTED` and recomputes the reviewed count, so the count always reflects the live set."

        Design: Difficulty/non_linear_state_machine/evaluation_reopen_cycle
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        patch_evaluation(evaluation["id"], evaluation["version"],
                         analysis_notes="Borrower downgraded after covenant breach; collateral-based reserve appropriate.")
        submit_evaluation(evaluation["id"])
        review_evaluation(evaluation["id"])
        validate_success(api.reopen_individual_evaluation(
            evaluation["id"], {"reopen_reason": "Re-verify collateral appraisal date"},
            chief_credit_officer_headers,
        ), 200)

        data = validate_success(
            api.review_individual_evaluation(evaluation["id"], chief_credit_officer_headers), 200
        )
        assert data["status"] == "REVIEWED"
        assert get_run(env.run["id"])["reviewed_evaluation_count"] == 1


class TestEvaluationCountConservation:
    def test_evaluation_count_conserved_through_review_cycle(self, api, chief_credit_officer_headers):
        """PRD §3.6: "One individual evaluation is created for every `ACTIVE` loan whose `individually_evaluated` flag is true — each starting in `DRAFT` with method `COLLATERAL_FAIR_VALUE` and its `collateral_value_cents` copied from the loan — and `individual_evaluation_count` records how many were created."
        PRD §3.7: "Reopening, also by a `ChiefCreditOfficer` and carrying a `reopen_reason`, returns the evaluation to `SUBMITTED` and recomputes the reviewed count, so the count always reflects the live set."

        Design: Difficulty/compensating_invariant/evaluation_review_reopen_conserves_count
        """
        env = executed_individual_run()
        assert env.run["individual_evaluation_count"] == 1
        evaluation = get_single_evaluation(env.run["id"])

        patch_evaluation(evaluation["id"], evaluation["version"],
                         analysis_notes="Collateral-based reserve documented.")
        submit_evaluation(evaluation["id"])
        review_evaluation(evaluation["id"])
        api.reopen_individual_evaluation(
            evaluation["id"], {"reopen_reason": "Reconfirm appraisal"},
            chief_credit_officer_headers,
        )
        review_evaluation(evaluation["id"])

        run = get_run(env.run["id"])
        assert run["individual_evaluation_count"] == 1, (
            "the review/reopen cycle neither creates nor destroys evaluations"
        )
        assert len(list_run_evaluations(env.run["id"])) == 1

    def test_reviewed_count_reflects_live_set(self, api, chief_credit_officer_headers):
        """PRD §3.7: "Review by a `ChiefCreditOfficer` recomputes the run's `reviewed_evaluation_count` — the number of the run's evaluations currently in `REVIEWED` — and re-syncs the same run totals."

        Design: Difficulty/compensating_invariant/evaluation_review_reopen_conserves_count
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        patch_evaluation(evaluation["id"], evaluation["version"],
                         analysis_notes="Collateral-based reserve documented.")
        submit_evaluation(evaluation["id"])
        review_evaluation(evaluation["id"])
        assert get_run(env.run["id"])["reviewed_evaluation_count"] == 1

        api.reopen_individual_evaluation(
            evaluation["id"], {"reopen_reason": "Reconfirm appraisal"},
            chief_credit_officer_headers,
        )
        assert get_run(env.run["id"])["reviewed_evaluation_count"] == 0

        review_evaluation(evaluation["id"])
        run = get_run(env.run["id"])
        assert run["reviewed_evaluation_count"] == 1
        assert run["individual_evaluation_count"] == 1


class TestEvaluationConcurrency:
    def test_occ_stale_evaluation_version_rejected(self, api, credit_analyst_headers):
        """PRD §2.7: "Updating an individual evaluation requires the request to carry `expected_evaluation_version`, a non-optional input holding the evaluation's `version` as the client last observed it. If the evaluation's current `version` has advanced since then, the update is rejected with `ERR_EVALUATION_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_evaluation_version_rejected
        """
        env = executed_individual_run()
        evaluation = get_single_evaluation(env.run["id"])
        observed_version = evaluation["version"]

        first = validate_success(api.patch_individual_evaluation(
            evaluation["id"],
            {"expected_evaluation_version": observed_version,
             "analysis_notes": "Initial analysis notes documented here with sufficient detail."},
            credit_analyst_headers,
        ), 200)
        assert first["version"] == observed_version + 1

        stale = api.patch_individual_evaluation(
            evaluation["id"],
            {"expected_evaluation_version": observed_version,
             "collateral_value_cents": 400_000},
            credit_analyst_headers,
        )
        validate_error(stale, ApiErrorId.ERR_EVALUATION_STALE_VERSION, 412)

        reread = validate_success(
            api.get_individual_evaluation(evaluation["id"], credit_analyst_headers), 200
        )
        assert reread["collateral_value_cents"] == 460_000, (
            "the stale write must not be applied"
        )

    def test_derived_resync_on_evaluation_patch(self, api):
        """PRD §3.7: "Every such update must carry the OCC guard `expected_evaluation_version` per §2.7, and every accepted update recomputes the evaluation's `specific_reserve_cents`, re-syncs the parent run's `individual_reserve_cents` and `total_allowance_cents`, and increments the evaluation's `version`."

        Design: Corner/cross_cutting_layers/derived_resync_on_evaluation_patch
        """
        env = executed_individual_run()
        assert env.run["individual_reserve_cents"] == 86_000
        evaluation = get_single_evaluation(env.run["id"])

        patch_evaluation(
            evaluation["id"], evaluation["version"],
            method="DISCOUNTED_CASH_FLOW",
            expected_quarterly_cash_flows_cents=DCF_FLOWS,
            discount_rate_bps=300,
        )

        run = get_run(env.run["id"])
        assert run["individual_reserve_cents"] == 16_777
        assert run["total_allowance_cents"] == (
            env.run["total_allowance_cents"] - 86_000 + 16_777
        ), "total_allowance_cents re-syncs by the same delta"


class TestEvaluationListing:
    def test_individual_evaluations_filter_by_run(self, api, credit_analyst_headers):
        """PRD §3.7: "Evaluations can be listed with `run_id`, `loan_id`, and `status` filters, which is how an analyst inventories what a run still owes."

        Design: Corner/endpoints/individual_evaluations_filter_by_run
        """
        env = setup_run_environment(
            segment_specs=[{"name": "SmallBiz Subprime", "product_type": "SMALL_BUSINESS",
                            "risk_rating_band": "SUBPRIME", "vintage_year": 2023}],
            loan_specs=[substandard_loan_spec()],
        )
        execute_run(env.run["id"])
        run_2 = create_draft_run(
            env.model["id"],
            [{"scenario_id": env.scenarios[0]["id"], "weight_bps": 10_000}],
            as_of_period="2026-Q2",
        )
        execute_run(run_2["id"])

        filtered, meta = validate_paginated(api.list_individual_evaluations(
            credit_analyst_headers, params={"run_id": env.run["id"]}
        ))
        assert len(filtered) == 1
        assert filtered[0]["run_id"] == env.run["id"]
        assert_individual_evaluation(filtered[0])

        all_rows, meta_all = validate_paginated(
            api.list_individual_evaluations(credit_analyst_headers)
        )
        assert len(all_rows) == 2
        assert meta_all["total_count"] == 2
