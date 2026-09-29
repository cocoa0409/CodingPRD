"""Lifecycle transitions: the legal hops, the refused ones and the counters they move.

Four entities in this service carry a state machine, and this module walks the
transitions that decide whether work may proceed: a data window opening, sealing
and reopening; a model run's fit and validation dimensions advancing on separate
triggers; an experiment's draft-to-in-market path; and a budget scenario arriving
at its terminal invalidated state.

Every refusal here is attributable to the source state of the row being acted on
rather than to anything in the request body — each test therefore either issues
the identical call from two different states, or arranges the setup so that every
other precondition of the action is already satisfied. The side effects a legal
transition owns (the status itself, the mutation counter, the derived window
counters, the market's recomputed posture) are asserted alongside the status, so
a transition that lands in the right state while forgetting its bookkeeping is
still caught.
"""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dec(value) -> Decimal:
    """A JSON number as an exact decimal, so pinned figures compare exactly."""
    return Decimal(str(value))


# The reason text a reopen carries; the identical body is replayed from two
# different source states so only the state can explain the different answers.
_REOPEN_REASON = "Vendor restated August spend."

# An instant strictly after the canonical experiment's start_date, so that the
# calendar precondition of going in market is already satisfied.
_CLOCK_AFTER_EXPERIMENT_START = "2026-09-08T00:00:00Z"

# The restated figure for the first A_SEARCH period, filed over the incumbent
# 400000 the canonical chain already wrote for that channel-period.
_RESTATED_SPEND_CENTS = 450_000
_RESTATED_IMPRESSIONS = 4_500

# The window counters after each of the four sales writes on a four-period
# window: the running count, the completeness percentage and the row version.
_SALES_COUNTER_WALK = (
    (1, 25.00, 2),
    (2, 50.00, 3),
    (3, 75.00, 4),
    (4, 100.00, 5),
)


def _second_published_run(api, ctx):
    """A second run over the same sealed window, fitted, validated and published.

    It names the same two channels under the same carryover mode as the run
    already published, so its return vector matches the incumbent's exactly and
    the publication clears the stability floor without an override.
    """
    run = fixtures.create_run(api, ctx)
    validate_success(api.fit_model_run(run["id"], test_users.MODELER))
    validate_success(api.validate_model_run(run["id"], test_users.MODELER))
    return validate_success(
        api.publish_model_run(run["id"], test_users.ANALYTICS_LEAD)
    )


def test_seal_from_open_moves_to_sealed_without_lifting_the_posture(api):
    """PRD 3.3: "A `DataEngineer` may seal a window that is in `OPEN` or `REOPENED`
    status; sealing one that is already `SEALED` is `ERR_DATA_WINDOW_INVALID_STATE`."
    PRD 3.3: "Sealing sets `status` to `SEALED`, bumps the window's `version`, and
    recomputes the market's posture."
    PRD 2.8: "Second: if the market has no model run whose `publication_status` is
    `PUBLISHED`, or that published run's `calibration_status` is `STALE`, or the
    market has no data window in `SEALED` status, the posture is `RESTRICTED`."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by one on every mutation of that row, including mutations caused
    indirectly by a cascade fired from another resource."

    Design: Corner/state_machines/data_window_seal_from_open_valid_transition
    """
    ctx = fixtures.window_with_observations(api)
    window_id = ctx["window"]["id"]
    market_id = ctx["market"]["id"]
    fixtures.set_clock(api, fixtures.CLOCK_WINDOW_ELAPSED)

    sealed = validate_success(
        api.seal_data_window(window_id, test_users.DATA_ENGINEER), 200
    )

    assertions.assert_data_window(sealed)
    assert sealed["status"] == "SEALED", sealed["status"]
    assert sealed["version"] == fixtures.F1_WINDOW_VERSION_AFTER_SEAL, sealed["version"]
    assert sealed["sales_period_count"] == 4, sealed["sales_period_count"]
    assert sealed["spend_observation_count"] == 8, sealed["spend_observation_count"]
    assert _dec(sealed["lag_completeness_pct"]) == _dec(100.00), sealed[
        "lag_completeness_pct"
    ]
    assert sealed["reopen_count"] == 0, sealed["reopen_count"]
    assert sealed["reopen_reason"] is None, sealed["reopen_reason"]

    # A SEALED window is necessary but not sufficient: with no PUBLISHED run the
    # second branch of the posture formula still answers RESTRICTED.
    market = validate_success(api.get_market(market_id, test_users.DATA_ENGINEER))
    assert market["data_posture"] == "RESTRICTED", market["data_posture"]

    rows, meta = validate_paginated(
        api.list_data_windows(
            test_users.DATA_ENGINEER, {"market_id": market_id, "status": "SEALED"}
        )
    )
    assertions.assert_page_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [window_id], rows


def test_experiment_create_lands_in_draft_with_power_deferred(api):
    """PRD 3.6: "The draft is created in `DRAFT` with `redesign_count` 0 and with the
    acting operator captured in `designed_by_user_id` — the comparand every later
    decision on this experiment is measured against."
    PRD 3.6: "A successful lock freezes `power_index` and `computed_power` onto the
    row, sets `status` to `DESIGN_LOCKED` and increments `version`."
    PRD 3.6: "For an `AUDIENCE_SPLIT` design it also copies
    `planned_treatment_population` into `treatment_population` and
    `planned_control_population` into `control_population`, because that design has
    nothing further to enlist."
    PRD 3.6: "This estimator removes the control arm's own pre-to-post drift, and
    `synthetic_control_weight` is not derived at all under it — the field stays null."

    Design: Corner/state_machines/experiment_initial_state_is_draft
    """
    ctx = fixtures.market_with_channels(api)

    experiment = validate_success(
        api.create_experiment(
            factories.experiment_payload(
                ctx["market"]["id"], ctx["a_search"]["id"]
            ),
            test_users.EXPERIMENT_DESIGNER,
        ),
        201,
    )

    assertions.assert_experiment(experiment)
    assert experiment["status"] == "DRAFT", experiment["status"]
    assert experiment["redesign_count"] == 0, experiment["redesign_count"]
    assert experiment["designed_by_user_id"] == test_users.EXPERIMENT_DESIGNER_ID, (
        experiment["designed_by_user_id"]
    )
    assert experiment["version"] == 1, experiment["version"]

    # The planned figures are stored, but the realised arms and the power pair are
    # only written by the lock, so nothing computed exists yet.
    assert (
        experiment["planned_treatment_population"]
        == factories.EXPERIMENT_ARM_POPULATION
    ), experiment["planned_treatment_population"]
    assert (
        experiment["planned_control_population"] == factories.EXPERIMENT_ARM_POPULATION
    ), experiment["planned_control_population"]
    assert experiment["treatment_population"] == 0, experiment["treatment_population"]
    assert experiment["control_population"] == 0, experiment["control_population"]
    assert experiment["power_index"] is None, experiment["power_index"]
    assert experiment["computed_power"] is None, experiment["computed_power"]

    for field in (
        "measured_lift_pct",
        "lift_ci_half_width_pct",
        "lift_ci_low_pct",
        "lift_ci_high_pct",
        "synthetic_control_weight",
    ):
        assert experiment[field] is None, f"{field} == {experiment[field]!r}"


def test_reopen_from_open_rejected_then_accepted_after_the_seal(api):
    """PRD 3.3: "**Reopening** is the acknowledged data-integrity breach, and it is
    only available from `SEALED` — reopening an `OPEN` or already-`REOPENED` window is
    `ERR_DATA_WINDOW_INVALID_STATE`."
    PRD 3.3: "The request carries a single field, `reason`, whose text is stored on the
    window as `reopen_reason`, replacing any justification recorded by a previous
    reopen. The transition sets `status` to `REOPENED`, increases `reopen_count` by
    one, and bumps `version`."
    PRD 2.8: "First: if any data window belonging to the market is in `REOPENED`
    status, the posture is `FROZEN`."

    Design: Corner/state_machines/data_window_reopen_from_open_rejected
    """
    ctx = fixtures.window_with_observations(api)
    window_id = ctx["window"]["id"]
    market_id = ctx["market"]["id"]
    fixtures.set_clock(api, fixtures.CLOCK_WINDOW_ELAPSED)
    body = factories.reopen_payload(_REOPEN_REASON)

    refused = api.reopen_data_window(window_id, body, test_users.DATA_ENGINEER)
    validate_error(refused, ApiErrorId.ERR_DATA_WINDOW_INVALID_STATE.value, 409)

    still_open = validate_success(
        api.get_data_window(window_id, test_users.DATA_ENGINEER)
    )
    assert still_open["status"] == "OPEN", still_open["status"]
    assert still_open["reopen_count"] == 0, still_open["reopen_count"]
    assert still_open["reopen_reason"] is None, still_open["reopen_reason"]
    assert still_open["version"] == fixtures.F1_WINDOW_VERSION_AFTER_SPEND, still_open[
        "version"
    ]

    sealed = validate_success(
        api.seal_data_window(window_id, test_users.DATA_ENGINEER), 200
    )
    assert sealed["status"] == "SEALED", sealed["status"]

    # The identical body now succeeds, so the source state is the discriminator.
    reopened = validate_success(
        api.reopen_data_window(window_id, body, test_users.DATA_ENGINEER), 200
    )
    assert reopened["status"] == "REOPENED", reopened["status"]
    assert reopened["reopen_count"] == 1, reopened["reopen_count"]
    assert reopened["reopen_reason"] == _REOPEN_REASON, reopened["reopen_reason"]

    market = validate_success(api.get_market(market_id, test_users.DATA_ENGINEER))
    assert market["data_posture"] == "FROZEN", market["data_posture"]


def test_validate_before_fit_rejected_then_passes_once_fitted(api):
    """PRD 3.5: "Validation is a separate `Modeler` operation over the
    `validation_status` dimension, available only while `fit_status` is `FITTED`;
    attempting it on a run that is still `PENDING` or has gone `STALE_FIT` is
    `ERR_MODEL_RUN_INVALID_STATE`."
    PRD 3.4: "A newly created run reports `fit_status` `PENDING`, `validation_status`
    `UNVALIDATED`, `calibration_status` `NOT_REQUIRED` and `publication_status`
    `UNPUBLISHED`."
    PRD 3.4: "The run then sets `fit_status` to `FITTED`, resets `validation_status` to
    `UNVALIDATED`, clears `holdout_mape_pct` to null, records the acting operator in
    `fitted_by_user_id`, and increments its `version`."
    PRD 3.5: "`validation_status` becomes `HOLDOUT_PASSED` when `holdout_mape_pct` is
    at most 12.00 and `HOLDOUT_FAILED` when it is above 12.00."
    PRD 3.4: "A successful fit writes one decomposition row per included channel,
    created in ascending `channel_code` order, each with `is_current` true and with
    `calibrated_contribution_units` and `calibrated_contribution_revenue_cents`
    initially equal to their uncalibrated counterparts"

    Design: Corner/state_machines/model_run_validate_before_fit_rejected
    """
    ctx = fixtures.sealed_window(api)
    run = fixtures.create_run(api, ctx)
    assertions.assert_run_state(run, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED")

    refused = api.validate_model_run(run["id"], test_users.MODELER)
    validate_error(refused, ApiErrorId.ERR_MODEL_RUN_INVALID_STATE.value, 409)

    untouched = validate_success(api.get_model_run(run["id"], test_users.MODELER))
    assertions.assert_run_state(
        untouched, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    assertions.assert_version_unchanged(run, untouched)

    fitted = validate_success(
        api.fit_model_run(run["id"], test_users.MODELER), 200
    )
    assert fitted["fit_status"] == "FITTED", fitted["fit_status"]
    assert fitted["validation_status"] == "UNVALIDATED", fitted["validation_status"]
    assert fitted["holdout_mape_pct"] is None, fitted["holdout_mape_pct"]

    validated = validate_success(
        api.validate_model_run(run["id"], test_users.MODELER), 200
    )
    assert validated["validation_status"] == "HOLDOUT_PASSED", validated[
        "validation_status"
    ]
    assert _dec(validated["holdout_mape_pct"]) == _dec(
        fixtures.F1_EFFECT_HOLDOUT_MAPE_PCT
    ), validated["holdout_mape_pct"]
    assert validated["fit_status"] == "FITTED", validated["fit_status"]

    rows, meta = validate_paginated(
        api.list_channel_contributions(
            test_users.MODELER, {"model_run_id": run["id"]}
        )
    )
    assertions.assert_page_meta(meta, total_count=2)
    assert [row["channel_id"] for row in rows] == [
        ctx["a_search"]["id"],
        ctx["b_social"]["id"],
    ], "the fit writes its rows in ascending channel_code order"
    for row in rows:
        assert row["is_current"] is True, row


def test_start_from_draft_rejected_although_the_clock_has_passed_start_date(api):
    """PRD 3.6: "`CLOSED` is terminal; every action invoked against a closed experiment
    answers `ERR_EXPERIMENT_INVALID_STATE`, as does any action invoked from a state
    that has no such transition."
    PRD 3.6: "An `AUDIENCE_SPLIT` experiment reaches `RUNNING` straight from
    `DESIGN_LOCKED`, and that step (re)asserts `treatment_population` from
    `planned_treatment_population` and `control_population` from
    `planned_control_population`."
    PRD 3.6: "Either way the current logical clock must have reached `start_date`;
    earlier than that is `ERR_EXPERIMENT_NOT_STARTED`."

    Design: Corner/state_machines/experiment_start_from_draft_rejected
    """
    ctx = fixtures.market_with_channels(api)
    experiment = fixtures.create_experiment(api, ctx)
    assert experiment["status"] == "DRAFT", experiment["status"]

    # The clock sits strictly after start_date, so the calendar precondition of
    # going in market is already met and only the source state is wrong.
    fixtures.set_clock(api, _CLOCK_AFTER_EXPERIMENT_START)

    refused = api.start_experiment(experiment["id"], test_users.EXPERIMENT_DESIGNER)
    validate_error(refused, ApiErrorId.ERR_EXPERIMENT_INVALID_STATE.value, 409)

    untouched = validate_success(
        api.get_experiment(experiment["id"], test_users.EXPERIMENT_DESIGNER)
    )
    assert untouched["status"] == "DRAFT", untouched["status"]
    assert untouched["treatment_population"] == 0, untouched["treatment_population"]
    assert untouched["control_population"] == 0, untouched["control_population"]
    assert untouched["version"] == 1, untouched["version"]


def test_sealing_an_already_sealed_window_is_refused_and_bumps_nothing(api):
    """PRD 3.3: "A `DataEngineer` may seal a window that is in `OPEN` or `REOPENED`
    status; sealing one that is already `SEALED` is `ERR_DATA_WINDOW_INVALID_STATE`."
    PRD 3.3: "Sealing sets `status` to `SEALED`, bumps the window's `version`, and
    recomputes the market's posture."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by one on every mutation of that row, including mutations caused
    indirectly by a cascade fired from another resource."

    Design: Corner/state_machines/data_window_seal_twice_rejected
    """
    ctx = fixtures.sealed_window(api)
    window_id = ctx["window"]["id"]

    before = validate_success(
        api.get_data_window(window_id, test_users.DATA_ENGINEER)
    )
    assert before["status"] == "SEALED", before["status"]
    assert before["version"] == fixtures.F1_WINDOW_VERSION_AFTER_SEAL, before["version"]

    retry = api.seal_data_window(window_id, test_users.DATA_ENGINEER)
    validate_error(retry, ApiErrorId.ERR_DATA_WINDOW_INVALID_STATE.value, 409)

    after = validate_success(api.get_data_window(window_id, test_users.DATA_ENGINEER))
    assertions.assert_version_unchanged(before, after)
    assert after["status"] == "SEALED", after["status"]
    assert after["reopen_count"] == 0, after["reopen_count"]

    market = validate_success(
        api.get_market(ctx["market"]["id"], test_users.DATA_ENGINEER)
    )
    assert market["data_posture"] == "RESTRICTED", market["data_posture"]


def test_validate_branches_to_holdout_failed_and_blocks_publication(api):
    """PRD 3.5: "`validation_status` becomes `HOLDOUT_PASSED` when `holdout_mape_pct` is
    at most 12.00 and `HOLDOUT_FAILED` when it is above 12.00. Either way
    `holdout_mape_pct` is stored and the run's `version` increments."
    PRD 3.5: "It always succeeds as an operation and always moves `validation_status`
    out of `UNVALIDATED`, but it branches: the same request reaches `HOLDOUT_PASSED` or
    `HOLDOUT_FAILED` depending on the measured error, and only a run in
    `HOLDOUT_PASSED` may ever be published."
    PRD 3.5: "It requires `validation_status` to be exactly `HOLDOUT_PASSED`; an
    `UNVALIDATED` or `HOLDOUT_FAILED` run is refused with `ERR_HOLDOUT_NOT_PASSED`."
    PRD 2.8: "A market also publishes two convenience projections alongside its
    posture: `published_model_run_id`, which resolves to the `id` of the single run of
    that market whose `publication_status` is `PUBLISHED` and is null when no such run
    exists, and the population aggregates described in §3.1."

    Design: Corner/state_machines/model_run_validate_branches_to_holdout_failed
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="SPEND_PERIOD")
    run_id = ctx["run"]["id"]

    failed = validate_success(
        api.validate_model_run(run_id, test_users.MODELER), 200
    )
    assert failed["validation_status"] == "HOLDOUT_FAILED", failed["validation_status"]
    assert _dec(failed["holdout_mape_pct"]) == _dec(
        fixtures.F1_SPEND_HOLDOUT_MAPE_PCT
    ), failed["holdout_mape_pct"]
    # The backtest scores the fit; it never retracts it.
    assertions.assert_run_state(
        failed, "FITTED", "HOLDOUT_FAILED", "NOT_REQUIRED", "UNPUBLISHED"
    )

    refused = api.publish_model_run(run_id, test_users.ANALYTICS_LEAD)
    validate_error(refused, ApiErrorId.ERR_HOLDOUT_NOT_PASSED.value, 409)

    after = validate_success(api.get_model_run(run_id, test_users.MODELER))
    assert after["publication_status"] == "UNPUBLISHED", after["publication_status"]

    market = validate_success(
        api.get_market(ctx["market"]["id"], test_users.ANALYTICS_LEAD)
    )
    assert market["published_model_run_id"] is None, market["published_model_run_id"]
    assert market["data_posture"] == "RESTRICTED", market["data_posture"]


def test_each_sales_write_reconciles_the_window_counters_in_the_same_request(api):
    """PRD 3.2: "The parent window then increases its `sales_period_count` by one and
    recomputes `lag_completeness_pct` as one hundred multiplied by
    `sales_period_count`, divided by `expected_period_count`, rounded half-up to two
    decimal places — which, because each period admits at most one sales row, is
    exactly the share of the window's expected periods that carry a sales observation."
    PRD 3.2: "The window's `version` is incremented."
    PRD 3.2: "A new window opens in `OPEN` status with `sales_period_count`,
    `spend_observation_count` and `lag_completeness_pct` all at zero, `reopen_count` at
    0 and `reopen_reason` null."

    Design: Corner/state_machines/sales_observation_write_bumps_window_counters
    """
    market = fixtures.create_market(api)
    window = fixtures.create_data_window(api, market["id"])
    window_id = window["id"]
    assert window["expected_period_count"] == 4, window["expected_period_count"]
    assert window["sales_period_count"] == 0, window["sales_period_count"]

    walk = zip(
        factories.WINDOW_PERIODS, factories.F1_SALES_ROWS, _SALES_COUNTER_WALK
    )
    for period, row, (count, completeness_pct, version) in walk:
        validate_success(
            api.create_sales_observation(
                factories.sales_observation_payload(
                    window_id, period, row["units_sold"], row["revenue_cents"]
                ),
                test_users.DATA_ENGINEER,
            ),
            201,
        )

        seen = validate_success(
            api.get_data_window(window_id, test_users.DATA_ENGINEER)
        )
        assert seen["sales_period_count"] == count, (period, seen["sales_period_count"])
        assert _dec(seen["lag_completeness_pct"]) == _dec(completeness_pct), (
            period,
            seen["lag_completeness_pct"],
        )
        assert seen["version"] == version, (period, seen["version"])
        assert seen["spend_observation_count"] == 0, seen["spend_observation_count"]
        # Reconciling a derived counter is not a state transition.
        assert seen["status"] == "OPEN", seen["status"]


def test_spend_restatement_supersedes_the_incumbent_without_deleting_it(api):
    """PRD 3.2: "The incumbent's `superseded_by_id` is set to the new row's identifier,
    and the new row's `is_restatement` becomes true."
    PRD 3.2: "When no incumbent existed, the new row's `is_restatement` is false and its
    `superseded_by_id` stays null."
    PRD 3.2: "A superseded row is never deleted — it remains readable individually, and
    appears in list results only when `include_superseded` is requested, which is
    otherwise excluded by default."
    PRD 3.2: "Every accepted spend write recomputes the parent window's
    `spend_observation_count` over its non-superseded rows only, increments the window's
    `version`, and stamps the observation's `data_window_version_after` with the
    post-write value."

    Design: Corner/state_machines/spend_observation_restatement_supersedes_incumbent
    """
    ctx = fixtures.window_with_observations(api)
    window_id = ctx["window"]["id"]
    a_search_id = ctx["a_search"]["id"]
    incumbent = ctx["spend"][0]
    version_after_eight = ctx["spend"][-1]["data_window_version_after"]

    restatement = validate_success(
        api.create_spend_observation(
            factories.spend_observation_payload(
                window_id,
                a_search_id,
                factories.WINDOW_PERIODS[0],
                _RESTATED_SPEND_CENTS,
                version_after_eight,
                impressions=_RESTATED_IMPRESSIONS,
            ),
            test_users.DATA_ENGINEER,
        ),
        201,
    )

    assertions.assert_spend_observation(restatement)
    assert restatement["is_restatement"] is True, restatement["is_restatement"]
    assert restatement["spend_cents"] == _RESTATED_SPEND_CENTS, restatement["spend_cents"]
    assert restatement["superseded_by_id"] is None, restatement["superseded_by_id"]
    assert restatement["data_window_version_after"] == version_after_eight + 1, (
        restatement["data_window_version_after"]
    )

    # The incumbent survives, individually readable, pointing forward at its successor.
    kept = validate_success(
        api.get_spend_observation(incumbent["id"], test_users.DATA_ENGINEER)
    )
    assert kept["spend_cents"] == factories.F1_SPEND_A_SEARCH[0]["spend_cents"], kept[
        "spend_cents"
    ]
    assert kept["is_restatement"] is False, kept["is_restatement"]
    assert kept["superseded_by_id"] == restatement["id"], kept["superseded_by_id"]

    window = validate_success(
        api.get_data_window(window_id, test_users.DATA_ENGINEER)
    )
    assert window["spend_observation_count"] == 8, window["spend_observation_count"]
    assert window["version"] == restatement["data_window_version_after"], window[
        "version"
    ]

    live, live_meta = validate_paginated(
        api.list_spend_observations(
            test_users.DATA_ENGINEER,
            {"data_window_id": window_id, "channel_id": a_search_id},
        )
    )
    assertions.assert_page_meta(live_meta, total_count=4)
    assert incumbent["id"] not in [row["id"] for row in live], live

    everything, all_meta = validate_paginated(
        api.list_spend_observations(
            test_users.DATA_ENGINEER,
            {
                "data_window_id": window_id,
                "channel_id": a_search_id,
                "include_superseded": "true",
            },
        )
    )
    assertions.assert_page_meta(all_meta, total_count=5)
    assert incumbent["id"] in [row["id"] for row in everything], everything


def test_invalidated_scenario_refuses_all_three_actions_and_freezes_its_figures(api):
    """PRD 3.5: "A budget scenario that has gone `INVALIDATED` keeps its computed
    allocation and projection figures exactly as the optimizer left them, deliberately
    not reset, so that the plan that was almost approved stays auditable; optimizing,
    reverting and approving all answer `ERR_BUDGET_SCENARIO_INVALID_STATE` from there."
    PRD 3.5: "Its first hop moves the market's previously published run to
    `publication_status` `SUPERSEDED`, which is terminal: no operation returns a run
    from `SUPERSEDED`."
    PRD 3.5: "Its third hop, caused by the second, moves every budget scenario built on
    the superseded run whose status is `OPTIMIZED` or `APPROVED` to `INVALIDATED`."
    PRD 3.8: "And when the decomposition rows the scenario was built on stop being
    current — because the training window was reopened or the run was superseded — a
    scenario in `OPTIMIZED` or `APPROVED` moves to `INVALIDATED`, which is terminal."

    Design: Corner/state_machines/budget_scenario_invalidated_is_terminal
    """
    ctx = fixtures.optimized_scenario(api)
    scenario_id = ctx["scenario"]["id"]
    incumbent_run_id = ctx["run"]["id"]

    _second_published_run(api, ctx)

    displaced = validate_success(
        api.get_model_run(incumbent_run_id, test_users.MODELER)
    )
    assert displaced["publication_status"] == "SUPERSEDED", displaced[
        "publication_status"
    ]
    invalidated = validate_success(
        api.get_budget_scenario(scenario_id, test_users.BRAND_PLANNER)
    )
    assert invalidated["status"] == "INVALIDATED", invalidated["status"]

    validate_error(
        api.optimize_budget_scenario(scenario_id, test_users.BRAND_PLANNER),
        ApiErrorId.ERR_BUDGET_SCENARIO_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.revert_optimization(scenario_id, test_users.BRAND_PLANNER),
        ApiErrorId.ERR_BUDGET_SCENARIO_INVALID_STATE.value,
        409,
    )
    # The lead is not the scenario's creator and the run behind it is no longer
    # published, yet the scenario's own state precondition is what answers.
    validate_error(
        api.approve_budget_scenario(scenario_id, test_users.ANALYTICS_LEAD),
        ApiErrorId.ERR_BUDGET_SCENARIO_INVALID_STATE.value,
        409,
    )

    frozen = validate_success(
        api.get_budget_scenario(scenario_id, test_users.BRAND_PLANNER)
    )
    assert frozen["status"] == "INVALIDATED", frozen["status"]
    assert frozen["allocated_total_cents"] == fixtures.F1_ALLOCATED_TOTAL_CENTS, frozen[
        "allocated_total_cents"
    ]
    assert frozen["reallocation_fee_cents"] == fixtures.F1_REALLOCATION_FEE_CENTS, frozen[
        "reallocation_fee_cents"
    ]
    assert frozen["unallocated_cents"] == fixtures.F1_UNALLOCATED_CENTS, frozen[
        "unallocated_cents"
    ]
    assert frozen["shifted_total_cents"] == fixtures.F1_SHIFTED_TOTAL_CENTS, frozen[
        "shifted_total_cents"
    ]

    rows = fixtures.allocations_of(api, scenario_id)
    by_channel = assertions.rows_by(rows, "channel_id")
    assert (
        by_channel[ctx["a_search"]["id"]]["allocated_cents"]
        == fixtures.F1_ALLOCATED_A_SEARCH_CENTS
    ), by_channel[ctx["a_search"]["id"]]
    assert (
        by_channel[ctx["b_social"]["id"]]["allocated_cents"]
        == fixtures.F1_ALLOCATED_B_SOCIAL_CENTS
    ), by_channel[ctx["b_social"]["id"]]
