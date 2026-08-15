"""Loss model governance, economic scenarios, back-testing, and refresh (PRD §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    adverse_scenario_payload,
    assert_backtest_result,
    assert_loss_model,
    backtest_payload,
    create_active_model,
    create_draft_model,
    create_draft_run,
    create_factor,
    create_loan,
    create_loan_payload,
    create_loss_model_payload,
    create_scenario,
    create_scenario_payload,
    create_segment,
    execute_run,
    finalized_baseline_run,
    finalized_weighted_run,
    get_model,
    prime_loan_spec,
    record_backtest,
    setup_run_environment,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestModelLifecycle:
    def test_invalid_reversion_config_rejected(self, api, model_validator_headers):
        """PRD §3.1: "The `reversion_period_quarters` completes the pair, and the three values are validated together: an `IMMEDIATE` method requires a reversion period of exactly zero, a `STRAIGHT_LINE` method requires a reversion period between one and four quarters, and the forecast horizon plus the reversion period together may never exceed eight quarters. A configuration violating any of these three rules is rejected with `ERR_INVALID_REVERSION_CONFIG` (HTTP 422)."

        Design: Corner/validations/invalid_reversion_config_rejected
        """
        immediate_with_period = api.create_loss_model(
            create_loss_model_payload(
                name="Bad-1", method="LOSS_RATE", forecast_period_quarters=2,
                reversion_method="IMMEDIATE", reversion_period_quarters=3,
                historical_lookback_quarters=8,
            ),
            model_validator_headers,
        )
        validate_error(immediate_with_period, ApiErrorId.ERR_INVALID_REVERSION_CONFIG, 422)

        over_horizon = api.create_loss_model(
            create_loss_model_payload(
                name="Bad-2", method="LOSS_RATE", forecast_period_quarters=6,
                reversion_method="STRAIGHT_LINE", reversion_period_quarters=3,
                historical_lookback_quarters=8,
            ),
            model_validator_headers,
        )
        validate_error(over_horizon, ApiErrorId.ERR_INVALID_REVERSION_CONFIG, 422)

    def test_initial_states_on_create(self, api, credit_analyst_headers):
        """PRD §3.1: "A new model is born in `DRAFT` with `version_label` set to `v1`, `parent_model_id` null, `consecutive_backtest_breach_count` zeroed, and `refresh_required` false."
        PRD §3.4: "New scenarios are born `ACTIVE`."
        PRD §3.5: "The new factor starts in `DRAFT`."
        PRD §3.3: "Creation does two things atomically: the loan starts life `ACTIVE` with `charged_off_total_cents` and `recovered_total_cents` zeroed, and the segment's `origination_total_cents` grows by the loan's amortized cost."
        PRD §3.6: "The run begins in `DRAFT` with all counters zeroed, and runs can be listed with `loss_model_id`, `status`, and `as_of_period` filters to survey the pipeline."

        Design: Corner/state_machines/initial_states_on_create
        """
        model = create_draft_model()
        assert model["status"] == "DRAFT"
        assert model["version_label"] == "v1"
        assert model["parent_model_id"] is None
        assert model["consecutive_backtest_breach_count"] == 0
        assert model["refresh_required"] is False

        scenario = create_scenario()
        assert scenario["status"] == "ACTIVE"

        segment = create_segment()
        factor = create_factor(segment["id"], factor_code="POLICY_CHANGE",
                               adjustment_bps=10,
                               effective_from_period="2026-Q1",
                               effective_to_period="2026-Q1")
        assert factor["status"] == "DRAFT"

        loan = create_loan(segment["id"])
        assert loan["status"] == "ACTIVE"
        assert loan["charged_off_total_cents"] == 0
        assert loan["recovered_total_cents"] == 0

        active = validate_success(api.activate_loss_model(model["id"], TEST_USERS["model_validator_headers"]), 200)
        assert active["status"] == "ACTIVE"
        run = create_draft_run(model["id"], [{"scenario_id": scenario["id"], "weight_bps": 10_000}])
        assert run["status"] == "DRAFT"

    def test_retire_model_in_use_rejected(self, api, model_validator_headers):
        """PRD §3.1: "Retiring a model outright moves it from `ACTIVE` to `RETIRED`, but only while no in-flight run references it: a run in `DRAFT`, `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` blocks retirement with `ERR_MODEL_IN_USE` (HTTP 409), while `FINALIZED` runs, being settled history, do not."

        Design: Corner/validations/retire_model_in_use_rejected
        """
        env = setup_run_environment(loan_specs=[])  # ACTIVE model + DRAFT run
        res = api.retire_loss_model(env.model["id"], model_validator_headers)
        validate_error(res, ApiErrorId.ERR_MODEL_IN_USE, 409)
        assert get_model(env.model["id"])["status"] == "ACTIVE"

    def test_execute_with_retired_model_rejected(self, api, model_validator_headers, credit_analyst_headers):
        """PRD §3.6: "Execution is where the estimate is computed, performed by a `CreditAnalyst` moving the run `DRAFT` → `EXECUTED`; the referenced model must still be `ACTIVE` at that moment, else `ERR_MODEL_NOT_ACTIVE`."
        PRD §3.1: "a `ModelValidator` activates a `DRAFT` model, moving it to `ACTIVE`, and any other loss model that happens to be `ACTIVE` at that moment is automatically retired to `RETIRED` — at most one model is ever in production."

        Design: Corner/validations/execute_with_retired_model_rejected
        """
        model_a = create_active_model(name="CECL-A")
        scenario = create_scenario()
        run = create_draft_run(model_a["id"], [{"scenario_id": scenario["id"], "weight_bps": 10_000}])

        model_b = create_active_model(
            name="CECL-B", method="VINTAGE", forecast_period_quarters=4,
            reversion_method="STRAIGHT_LINE", reversion_period_quarters=2,
            historical_lookback_quarters=12,
        )
        assert get_model(model_a["id"])["status"] == "RETIRED"
        assert get_model(model_b["id"])["status"] == "ACTIVE"

        res = api.execute_model_run(run["id"], credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_MODEL_NOT_ACTIVE, 409)


class TestScenarioWindows:
    def test_scenario_touching_windows_accepted(self, api, model_validator_headers):
        """PRD §3.4: "Touching is not overlapping — one scenario's `effective_to_period` may equal another's `effective_from_period`, because the first window stops just before the second begins."

        Design: Difficulty/resource_temporal_overlap/scenario_half_open_touching
        """
        first = create_scenario(name="Baseline H1", effective_from_period="2026-Q1",
                                effective_to_period="2026-Q3")
        res = api.create_economic_scenario(
            create_scenario_payload(name="Baseline H2", unemployment_rate_bps=520,
                                    gdp_growth_bps=190, effective_from_period="2026-Q3",
                                    effective_to_period="2027-Q1"),
            model_validator_headers,
        )
        data = validate_success(res, 201)
        assert data["status"] == "ACTIVE"
        assert data["id"] != first["id"]

    def test_scenario_overlapping_window_rejected(self, api, model_validator_headers):
        """PRD §3.4: "The window discipline is what keeps the scenario library coherent: among `ACTIVE` scenarios of the same `scenario_type`, the half-open windows may never overlap, and any attempt to create one that does is rejected with `ERR_SCENARIO_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/scenario_half_open_touching
        """
        create_scenario(name="Baseline H1", effective_from_period="2026-Q1",
                        effective_to_period="2026-Q3")
        # Half-open [2026-Q1, 2026-Q3) covers Q1 and Q2, so a new BASELINE
        # window starting at 2026-Q2 shares quarter Q2 and must be rejected.
        res = api.create_economic_scenario(
            create_scenario_payload(name="Baseline Overlap", unemployment_rate_bps=540,
                                    gdp_growth_bps=180, effective_from_period="2026-Q2",
                                    effective_to_period="2026-Q4"),
            model_validator_headers,
        )
        validate_error(res, ApiErrorId.ERR_SCENARIO_WINDOW_OVERLAP, 409)


class TestScenarioArchive:
    def test_archive_scenario_in_use_rejected(self, api, model_validator_headers):
        """PRD §3.4: "Archiving is blocked while any in-flight run — one in `DRAFT`, `EXECUTED`, `UNDER_REVIEW`, or `APPROVED` — still references the scenario in its `scenario_weights`, and such an attempt is rejected with `ERR_SCENARIO_IN_USE` (HTTP 409)."

        Design: Corner/validations/archive_scenario_in_use_rejected
        """
        env = setup_run_environment(loan_specs=[])  # DRAFT run pins the scenario
        scenario = env.scenarios[0]
        res = api.archive_economic_scenario(scenario["id"], model_validator_headers)
        validate_error(res, ApiErrorId.ERR_SCENARIO_IN_USE, 409)
        data = validate_success(api.get_economic_scenario(scenario["id"], model_validator_headers), 200)
        assert data["status"] == "ACTIVE"


class TestBacktesting:
    def test_backtest_without_finalized_run_rejected(self, api, model_validator_headers):
        """PRD §3.1: "When no run qualifies, the back-test is refused with `ERR_NO_FINALIZED_RUN` (HTTP 409)."

        Design: Corner/validations/backtest_without_finalized_run_rejected
        """
        model = create_active_model()
        res = api.create_backtest(model["id"], backtest_payload(actual_loss_rate_bps=300),
                                  model_validator_headers)
        validate_error(res, ApiErrorId.ERR_NO_FINALIZED_RUN, 409)

    def test_variance_exactly_150_is_pass(self, api, model_validator_headers):
        """PRD §3.1: "The `outcome` is `BREACH` when the absolute value of the variance is strictly greater than one hundred fifty basis points; a variance of exactly one hundred fifty basis points in either direction is still a `PASS`."
        PRD §3.1: "The `predicted_loss_rate_bps` is the selected run's `total_allowance_cents` multiplied by ten thousand and divided by its `total_exposure_cents`, rounded half-up to a whole basis point. The `variance_bps` is the supplied `actual_loss_rate_bps` minus that predicted rate."

        Design: Difficulty/boundary_precision_check/backtest_variance_strictly_greater
        """
        env = finalized_weighted_run()  # allowance 55000 / exposure 10000000 -> predicted 55
        data = validate_success(api.create_backtest(
            env.model["id"],
            backtest_payload(backtest_period="2026-Q1", actual_loss_rate_bps=205),
            model_validator_headers,
        ), 201)
        assert_backtest_result(data)
        assert data["predicted_loss_rate_bps"] == 55
        assert data["variance_bps"] == 150
        assert data["outcome"] == "PASS"

    def test_variance_151_is_breach(self, api, model_validator_headers):
        """PRD §3.1: "The `outcome` is `BREACH` when the absolute value of the variance is strictly greater than one hundred fifty basis points; a variance of exactly one hundred fifty basis points in either direction is still a `PASS`."

        Design: Difficulty/boundary_precision_check/backtest_variance_strictly_greater
        """
        env = finalized_weighted_run()
        data = validate_success(api.create_backtest(
            env.model["id"],
            backtest_payload(backtest_period="2026-Q1", actual_loss_rate_bps=206),
            model_validator_headers,
        ), 201)
        assert data["predicted_loss_rate_bps"] == 55
        assert data["variance_bps"] == 151
        assert data["outcome"] == "BREACH"

    def test_consecutive_breaches_set_refresh_required(self, api, model_validator_headers):
        """PRD §3.1: "On a `BREACH`, the model's `consecutive_backtest_breach_count` increments by one, and if the count thereby reaches two, the model's `refresh_required` flag is set true — the formal signal that the model can no longer be trusted without recalibration."

        Design: Difficulty/transitive_cascade/backtest_breach_refresh_chain
        """
        env = finalized_weighted_run()  # predicted 55 bps

        first = record_backtest(env.model["id"], backtest_period="2026-Q1",
                                actual_loss_rate_bps=300)
        assert first["outcome"] == "BREACH"  # |300 - 55| = 245 > 150
        mid = get_model(env.model["id"])
        assert mid["consecutive_backtest_breach_count"] == 1  # hop 1
        assert mid["refresh_required"] is False

        record_backtest(env.model["id"], backtest_period="2026-Q2",
                        actual_loss_rate_bps=300)
        after = get_model(env.model["id"])
        assert after["consecutive_backtest_breach_count"] == 2
        assert after["refresh_required"] is True              # hop 2

    def test_refresh_creates_successor_and_clears_breach_state(self, api, model_validator_headers):
        """PRD §3.1: "A refresh never mutates the old model's configuration; instead it creates a new loss model in `DRAFT` whose `parent_model_id` points back at the refreshed model, whose `version_label` increments the lineage — `v1` begets `v2`, `v2` begets `v3` — and whose configuration fields are copied from the parent. The refreshed model itself remains `ACTIVE`; its `refresh_required` flag clears to false and its `consecutive_backtest_breach_count` resets to zero."

        Design: Difficulty/transitive_cascade/backtest_breach_refresh_chain
        """
        env = finalized_weighted_run()
        record_backtest(env.model["id"], backtest_period="2026-Q1", actual_loss_rate_bps=300)
        record_backtest(env.model["id"], backtest_period="2026-Q2", actual_loss_rate_bps=300)
        assert get_model(env.model["id"])["refresh_required"] is True

        res = api.refresh_loss_model(env.model["id"], model_validator_headers)
        new_model = validate_success(res, 201)
        assert_loss_model(new_model)
        assert new_model["status"] == "DRAFT"
        assert new_model["parent_model_id"] == env.model["id"]
        assert new_model["version_label"] == "v2"

        old = get_model(env.model["id"])
        assert old["status"] == "ACTIVE"
        assert old["refresh_required"] is False
        assert old["consecutive_backtest_breach_count"] == 0

    def test_backtest_pass_resets_breach_counter(self, api, model_validator_headers):
        """PRD §3.1: "On a `PASS`, the count resets to zero while `refresh_required` is left untouched."
        PRD §3.1: "Refresh is the remediation path, and it is gated: refreshing a model whose `refresh_required` flag is false is rejected with `ERR_REFRESH_NOT_REQUIRED` (HTTP 409)."

        Design: Corner/calculations/backtest_pass_resets_breach_counter
        """
        env = finalized_weighted_run()  # predicted 55 bps
        record_backtest(env.model["id"], backtest_period="2026-Q1", actual_loss_rate_bps=300)
        passing = record_backtest(env.model["id"], backtest_period="2026-Q1",
                                  actual_loss_rate_bps=100)
        assert passing["outcome"] == "PASS"  # |100 - 55| = 45 <= 150
        record_backtest(env.model["id"], backtest_period="2026-Q2", actual_loss_rate_bps=300)

        model = get_model(env.model["id"])
        assert model["consecutive_backtest_breach_count"] == 1, (
            "BREACH/PASS/BREACH leaves the counter at 1, not 3"
        )
        assert model["refresh_required"] is False

        res = api.refresh_loss_model(env.model["id"], model_validator_headers)
        validate_error(res, ApiErrorId.ERR_REFRESH_NOT_REQUIRED, 409)

    def test_backtest_result_immutability(self, api, model_validator_headers):
        """PRD §2.4: "Back-test results are the one exception: a back-test result carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it, because a recorded back-test is an immutable observation that is never modified after creation."

        Design: Corner/entities/backtest_result_immutability
        """
        env = finalized_baseline_run()  # allowance 50000 / exposure 10000000 -> predicted 50
        data = validate_success(api.create_backtest(
            env.model["id"],
            backtest_payload(backtest_period="2026-Q1", actual_loss_rate_bps=60),
            model_validator_headers,
        ), 201)
        assert_backtest_result(data)  # asserts absence of updated_at / version
        assert data["outcome"] == "PASS"  # |60 - 50| = 10 <= 150
        assert data["predicted_loss_rate_bps"] == 50
