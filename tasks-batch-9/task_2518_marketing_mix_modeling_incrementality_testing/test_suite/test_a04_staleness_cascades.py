"""Two multi-hop staleness chains fired from two different transitions.

Accepting a readout makes the market's published run's calibration stale, which
makes the market's posture fall out of `OPEN`, which freezes the plans that were
built while it was open. Reopening a training window makes the run's fit stale,
which takes its decomposition rows out of currency, which invalidates the plans
those rows supported. Neither chain is a fan-out from the request: each hop is
observable only because the hop before it happened.

Every test builds its own preconditions from scratch: the harness relaunches the
API against an empty database before each one.
"""

from test_helpers import (
    assertions as a,
    factories as f,
    fixtures as fx,
    test_users as users,
    validate_paginated,
    validate_success,
)

# The second experiment runs on B_SOCIAL after the first one's washout tail, so
# the two never contend for the same channel-interval.
SECOND_EXPERIMENT_START = "2026-10-12T00:00:00Z"
SECOND_EXPERIMENT_END = "2026-11-09T00:00:00Z"


def _market_ready_for_a_second_acceptance(api):
    """A market with everything the accept cascade can possibly touch.

    The published run has been recalibrated, so its `calibration_status` is
    `CALIBRATED`; one reconciliation report stands `CURRENT` on the calibrated
    basis; one budget scenario has been optimized while the posture was `OPEN`;
    and a second readout is waiting on the market's other channel. The clock only
    ever moves forward: 2026-08-31, then 2026-09-07, then 2026-10-05, then the
    second experiment's own start and end dates.
    """
    ctx = fx.calibrated_run(api)
    ctx["report"] = fx.file_reconciliation_report(api, ctx)
    fx.scenario_with_allocations(api, ctx)
    fx.optimized_scenario(api, ctx)

    second = fx.create_experiment(
        api,
        ctx,
        channel_id=ctx["b_social"]["id"],
        start_date=SECOND_EXPERIMENT_START,
        end_date=SECOND_EXPERIMENT_END,
    )
    second = fx.locked_experiment(api, ctx, experiment=second)
    fx.set_clock(api, SECOND_EXPERIMENT_START)
    second = validate_success(
        api.start_experiment(second["id"], users.EXPERIMENT_DESIGNER)
    )
    fx.set_clock(api, SECOND_EXPERIMENT_END)
    ctx["second_experiment"] = validate_success(
        api.read_out_experiment(
            second["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
        )
    )
    return ctx


def _contribution_count(api, run_id, is_current):
    """How many decomposition rows of a run carry the given currency flag."""
    _, meta = validate_paginated(
        api.list_channel_contributions(
            users.MODELER, {"model_run_id": run_id, "is_current": is_current}
        )
    )
    return meta["total_count"]


def test_accepting_a_readout_moves_the_published_run_calibration_to_stale(api):
    """PRD §3.6: "Its first hop moves the market's published run, if its
    `calibration_status` is `CALIBRATED`, to `calibration_status` `STALE`: newly
    accepted experimental truth invalidates the correction that was derived from
    older truth."
    PRD §3.7: "A `CALIBRATED` published run falls to `STALE` when a new experiment
    readout is accepted in its market, as described in §3.6, and a `STALE` run
    returns to `PENDING_CALIBRATION` as soon as the next record is filed against
    it, from where recalibration can run again."
    PRD §3.4: "Those four dimensions evolve independently on different triggers,
    and no movement in one implies a movement in another except where this
    document says so."

    Design: Difficulty/transitive_cascade/accept_readout_cascades_calibration_staleness_to_budget_freeze
    """
    ctx = _market_ready_for_a_second_acceptance(api)
    run_before = ctx["run"]
    a.assert_run_state(run_before, "FITTED", "HOLDOUT_PASSED", "CALIBRATED", "PUBLISHED")
    assert ctx["market"]["data_posture"] == "OPEN", ctx["market"]["data_posture"]
    assert run_before["baseline_sales_units"] == fx.F1_CALIBRATED_BASELINE_UNITS, (
        "the recalibration pushed the withdrawn units back into the baseline"
    )

    accepted = validate_success(
        api.accept_experiment(ctx["second_experiment"]["id"], users.ANALYTICS_LEAD)
    )

    assert accepted["status"] == "ACCEPTED", accepted["status"]
    assert accepted["decided_by_user_id"] == users.ANALYTICS_LEAD_ID, accepted[
        "decided_by_user_id"
    ]
    run_after = fx.refresh_run(api, ctx)
    a.assert_run_state(run_after, "FITTED", "HOLDOUT_PASSED", "STALE", "PUBLISHED")
    assert run_after["baseline_sales_units"] == fx.F1_CALIBRATED_BASELINE_UNITS, (
        "staleness is a status, not a recomputation: the calibrated accounting "
        f"identity must stand, got {run_after['baseline_sales_units']!r}"
    )
    record = validate_success(
        api.get_calibration_record(ctx["calibration_record"]["id"], users.MODELER)
    )
    assert record["superseded"] is False, (
        "no later record was filed for that run-and-channel pair, so the "
        "existing one stays live even though the run's calibration went stale"
    )


def test_stale_calibration_flips_the_current_report_and_drops_the_posture_to_restricted(api):
    """PRD §3.6: "Its second hop, caused by the first, moves that run's
    reconciliation reports whose `status` is `CURRENT` to `STALE` and recomputes
    the market's `data_posture`, which falls from `OPEN` to `RESTRICTED` because
    the published run's calibration is now stale."
    PRD §2.8: "Second: if the market has no model run whose `publication_status`
    is `PUBLISHED`, or that published run's `calibration_status` is `STALE`, or
    the market has no data window in `SEALED` status, the posture is
    `RESTRICTED`. Otherwise the posture is `OPEN`."
    PRD §3.9: "It flips to `STALE` when its run becomes `SUPERSEDED` or when its
    run's `calibration_status` becomes `STALE`, and `STALE` is terminal — every
    computed variance field freezes at its filed value and a fresh report must be
    created against the new run rather than refreshing the old one in place."

    Design: Difficulty/transitive_cascade/accept_readout_cascades_calibration_staleness_to_budget_freeze
    """
    ctx = _market_ready_for_a_second_acceptance(api)
    report_before = ctx["report"]
    assert report_before["status"] == "CURRENT", report_before["status"]
    assert report_before["basis"] == "CALIBRATED", (
        "the report was filed against a CALIBRATED run, so it compares the "
        f"calibrated figures, got basis {report_before['basis']!r}"
    )
    assert (
        report_before["model_attributed_revenue_cents"]
        == fx.F1_CALIBRATED_MODEL_ATTRIBUTED_CENTS
    ), report_before["model_attributed_revenue_cents"]
    assert report_before["weighted_variance_pct"] == fx.F1_CALIBRATED_WEIGHTED_VARIANCE_PCT
    assert report_before["attribution_gap_flag"] == "MATERIAL", report_before[
        "attribution_gap_flag"
    ]

    validate_success(
        api.accept_experiment(ctx["second_experiment"]["id"], users.ANALYTICS_LEAD)
    )

    report_after = validate_success(
        api.get_reconciliation_report(report_before["id"], users.ANALYTICS_LEAD)
    )
    assert report_after["status"] == "STALE", (
        "the accept made the run's calibration stale, and a report standing on a "
        f"stale calibration goes stale with it, got {report_after['status']!r}"
    )
    assert report_after["basis"] == "CALIBRATED", "the filed basis is frozen too"
    assert (
        report_after["model_attributed_revenue_cents"]
        == fx.F1_CALIBRATED_MODEL_ATTRIBUTED_CENTS
    ), "every computed variance field freezes at its filed value"
    assert report_after["total_variance_cents"] == fx.F1_CALIBRATED_TOTAL_VARIANCE_CENTS
    assert report_after["weighted_variance_pct"] == fx.F1_CALIBRATED_WEIGHTED_VARIANCE_PCT
    assert report_after["attribution_gap_flag"] == "MATERIAL", report_after[
        "attribution_gap_flag"
    ]

    market_after = fx.refresh_market(api, ctx)
    assert market_after["data_posture"] == "RESTRICTED", (
        "no data window of this market is REOPENED, so the posture can only have "
        f"fallen as far as RESTRICTED, got {market_after['data_posture']!r}"
    )
    window_after = fx.refresh_window(api, ctx)
    assert window_after["status"] == "SEALED", (
        "the accept touched no window at all"
    )


def test_posture_leaving_open_freezes_the_optimized_scenario_and_leaves_the_draft_alone(api):
    """PRD §3.6: "Its third hop, caused by the posture leaving `OPEN`, moves every
    budget scenario of the market whose status is `OPTIMIZED` to `FROZEN`,
    resetting each of those scenarios' allocation rows' `allocated_cents` back to
    their `baseline_spend_cents` and zeroing the scenario's
    `reallocation_fee_cents` and `unallocated_cents`."
    PRD §3.8: "When the market's `data_posture` leaves `OPEN`, every scenario of
    that market in `OPTIMIZED` moves to `FROZEN`, with its allocations reset to
    baseline exactly as a revert would have done; a `DRAFT` scenario is
    deliberately not frozen, since it holds no optimizer output to unwind."
    PRD §2.10: "The first is fiscal: for every budget scenario, the sum of
    `allocated_total_cents`, `reallocation_fee_cents` and `unallocated_cents`
    equals `total_budget_cents` at every observable moment."

    Design: Difficulty/transitive_cascade/accept_readout_cascades_calibration_staleness_to_budget_freeze
    """
    ctx = _market_ready_for_a_second_acceptance(api)
    optimized = ctx["scenario"]
    assert optimized["status"] == "OPTIMIZED", optimized["status"]
    assert optimized["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS
    assert optimized["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS
    assert optimized["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS
    a.assert_budget_conservation(optimized)
    assert optimized["model_run_id"] == ctx["run"]["id"], (
        "the frozen plan is built on the published run, never on the experiment "
        "whose acceptance freezes it"
    )
    draft_before = fx.create_scenario(
        api,
        ctx,
        planning_start_date="2026-12-07T00:00:00Z",
        planning_end_date="2027-01-04T00:00:00Z",
    )
    fx.add_allocation(
        api, draft_before["id"], ctx["a_search"]["id"], f.BASELINE_A_SEARCH_CENTS
    )
    fx.add_allocation(
        api, draft_before["id"], ctx["b_social"]["id"], f.BASELINE_B_SOCIAL_CENTS
    )
    draft_before = validate_success(
        api.get_budget_scenario(draft_before["id"], users.BRAND_PLANNER)
    )
    assert draft_before["status"] == "DRAFT", draft_before["status"]

    validate_success(
        api.accept_experiment(ctx["second_experiment"]["id"], users.ANALYTICS_LEAD)
    )

    frozen = fx.refresh_scenario(api, ctx)
    assert frozen["status"] == "FROZEN", (
        "the plan was optimized while the posture was OPEN, so it freezes when "
        f"the posture leaves OPEN, got {frozen['status']!r}"
    )
    assert frozen["reallocation_fee_cents"] == 0, frozen["reallocation_fee_cents"]
    assert frozen["unallocated_cents"] == 0, frozen["unallocated_cents"]
    assert frozen["allocated_total_cents"] == f.SCENARIO_TOTAL_BUDGET_CENTS, (
        "with the fee and the unspent remainder both zeroed, the whole budget is "
        f"back on the rows, got {frozen['allocated_total_cents']!r}"
    )
    a.assert_budget_conservation(frozen)

    rows = a.rows_by(fx.allocations_of(api, frozen["id"]), "channel_id")
    a_row = rows[ctx["a_search"]["id"]]
    b_row = rows[ctx["b_social"]["id"]]
    assert a_row["allocated_cents"] == f.BASELINE_A_SEARCH_CENTS, a_row[
        "allocated_cents"
    ]
    assert b_row["allocated_cents"] == f.BASELINE_B_SOCIAL_CENTS, b_row[
        "allocated_cents"
    ]
    for row in (a_row, b_row):
        assert row["shifted_cents"] == 0, row["shifted_cents"]
        assert row["constraint_binding"] == "NONE", row["constraint_binding"]

    draft_after = validate_success(
        api.get_budget_scenario(draft_before["id"], users.BRAND_PLANNER)
    )
    assert draft_after["status"] == "DRAFT", (
        "a draft holds no optimizer output to unwind, so the freeze pass skips it"
    )
    a.assert_version_unchanged(draft_before, draft_after)


def test_reopening_the_training_window_makes_the_fitted_run_stale_and_unvalidated(api):
    """PRD §3.3: "The request carries a single field, `reason`, whose text is
    stored on the window as `reopen_reason`, replacing any justification recorded
    by a previous reopen."
    PRD §3.3: "The transition sets `status` to `REOPENED`, increases `reopen_count`
    by one, and bumps `version`."
    PRD §3.3: "The first hop reaches the runs: every model run whose training
    window is this one and whose `fit_status` is `FITTED` moves to `fit_status`
    `STALE_FIT` and simultaneously has its `validation_status` reset to
    `UNVALIDATED`, because a backtest against retracted data proves nothing."
    PRD §2.8: "A market also publishes two convenience projections alongside its
    posture: `published_model_run_id`, which resolves to the `id` of the single
    run of that market whose `publication_status` is `PUBLISHED` and is null when
    no such run exists, and the population aggregates described in §3.1."

    Design: Difficulty/transitive_cascade/window_reopen_cascades_stale_fit_to_scenario_invalidation
    """
    ctx = fx.optimized_scenario(api)
    window_before = ctx["window"]
    run_before = ctx["run"]
    assert window_before["status"] == "SEALED", window_before["status"]
    assert window_before["reopen_count"] == 0, window_before["reopen_count"]
    assert window_before["reopen_reason"] is None, window_before["reopen_reason"]
    a.assert_run_state(
        run_before, "FITTED", "HOLDOUT_PASSED", "NOT_REQUIRED", "PUBLISHED"
    )

    reason = "Media agency restated August search spend."
    reopened = validate_success(
        api.reopen_data_window(
            window_before["id"], f.reopen_payload(reason), users.DATA_ENGINEER
        )
    )

    assert reopened["status"] == "REOPENED", reopened["status"]
    assert reopened["reopen_count"] == 1, reopened["reopen_count"]
    assert reopened["reopen_reason"] == reason, reopened["reopen_reason"]
    assert reopened["version"] > window_before["version"], (
        "the acknowledged breach bumps the window's version"
    )

    run_after = fx.refresh_run(api, ctx)
    a.assert_run_state(
        run_after, "STALE_FIT", "UNVALIDATED", "NOT_REQUIRED", "PUBLISHED"
    )
    assert run_after["publication_status"] == "PUBLISHED", (
        "the reopen unwinds the fit and the backtest, never the publication "
        f"decision, got {run_after['publication_status']!r}"
    )
    market_after = fx.refresh_market(api, ctx)
    assert market_after["published_model_run_id"] == run_before["id"], (
        "the run is still the single PUBLISHED run of the market, so the market's "
        f"projection still resolves to it, got {market_after['published_model_run_id']!r}"
    )


def test_the_stale_fit_takes_every_decomposition_row_out_of_currency(api):
    """PRD §3.3: "The second hop, caused by the first, reaches those runs'
    decomposition rows: every `ChannelContribution` row belonging to each affected
    run has `is_current` set to false."
    PRD §3.4: "A row's `is_current` becomes false whenever its producing run's
    `fit_status` leaves `FITTED` or its `publication_status` becomes
    `SUPERSEDED`."
    PRD §3.4: "Decomposition rows are readable individually and listable filtered
    by `model_run_id`, by `channel_id`, by `is_current` and by
    `attribution_mode_used`."

    Design: Difficulty/transitive_cascade/window_reopen_cascades_stale_fit_to_scenario_invalidation
    """
    ctx = fx.optimized_scenario(api)
    run_id = ctx["run"]["id"]
    assert _contribution_count(api, run_id, "true") == 2, (
        "the fit wrote one current row per included channel"
    )
    assert _contribution_count(api, run_id, "false") == 0, (
        "nothing has taken those rows out of currency yet"
    )

    validate_success(
        api.reopen_data_window(
            ctx["window"]["id"], f.reopen_payload(), users.DATA_ENGINEER
        )
    )

    assert _contribution_count(api, run_id, "true") == 0, (
        "the run's fit_status left FITTED, so no row of it is current any more"
    )
    assert _contribution_count(api, run_id, "false") == 2, (
        "both rows survive the cascade and are still listable, just not current"
    )
    rows = a.rows_by(
        fx.contributions_of(api, run_id, is_current="false"), "channel_id"
    )
    for channel_id in (ctx["a_search"]["id"], ctx["b_social"]["id"]):
        assert rows[channel_id]["is_current"] is False, (
            "every row belonging to the affected run is flipped, not just the "
            f"channel whose spend was restated: {rows[channel_id]!r}"
        )


def test_rows_leaving_currency_invalidate_the_plan_and_keep_its_optimizer_figures(api):
    """PRD §3.3: "The third hop, caused by the second, reaches planning: every
    budget scenario whose model run is one of those runs and whose status is
    `OPTIMIZED` or `APPROVED` moves to `INVALIDATED`."
    PRD §3.3: "Separately, because a `REOPENED` window now exists, the market's
    posture is recomputed to `FROZEN`, and the fourth hop follows from that posture
    change: every remaining budget scenario of the *whole market* whose status is
    `OPTIMIZED` moves to `FROZEN`."
    PRD §3.5: "A budget scenario that has gone `INVALIDATED` keeps its computed
    allocation and projection figures exactly as the optimizer left them,
    deliberately not reset, so that the plan that was almost approved stays
    auditable; optimizing, reverting and approving all answer
    `ERR_BUDGET_SCENARIO_INVALID_STATE` from there."

    Design: Difficulty/transitive_cascade/window_reopen_cascades_stale_fit_to_scenario_invalidation
    """
    ctx = fx.optimized_scenario(api)
    optimized = ctx["scenario"]
    assert optimized["status"] == "OPTIMIZED", optimized["status"]
    assert optimized["model_run_id"] == ctx["run"]["id"], optimized["model_run_id"]

    validate_success(
        api.reopen_data_window(
            ctx["window"]["id"], f.reopen_payload(), users.DATA_ENGINEER
        )
    )

    scenario_after = fx.refresh_scenario(api, ctx)
    assert scenario_after["status"] == "INVALIDATED", (
        "the plan stood on decomposition rows that stopped being current, which "
        f"is terminal for it, got {scenario_after['status']!r}"
    )
    assert scenario_after["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS, (
        "an invalidated plan keeps the optimizer's figures: the market-wide freeze "
        "pass only touches scenarios still sitting in OPTIMIZED, and this one had "
        f"already left it, got {scenario_after['allocated_total_cents']!r}"
    )
    assert scenario_after["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS, (
        scenario_after["reallocation_fee_cents"]
    )
    assert scenario_after["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS, (
        scenario_after["unallocated_cents"]
    )
    assert scenario_after["shifted_total_cents"] == fx.F1_SHIFTED_TOTAL_CENTS, (
        scenario_after["shifted_total_cents"]
    )
    a.assert_budget_conservation(scenario_after)

    rows = a.rows_by(fx.allocations_of(api, scenario_after["id"]), "channel_id")
    assert (
        rows[ctx["a_search"]["id"]]["allocated_cents"] == fx.F1_ALLOCATED_A_SEARCH_CENTS
    ), rows[ctx["a_search"]["id"]]["allocated_cents"]
    assert (
        rows[ctx["b_social"]["id"]]["allocated_cents"] == fx.F1_ALLOCATED_B_SOCIAL_CENTS
    ), rows[ctx["b_social"]["id"]]["allocated_cents"]

    market_after = fx.refresh_market(api, ctx)
    assert market_after["data_posture"] == "FROZEN", (
        "a REOPENED window exists, which is the strictest posture branch, got "
        f"{market_after['data_posture']!r}"
    )
