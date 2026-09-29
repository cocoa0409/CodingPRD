"""Gates that read the state of a neighbouring entity rather than their own.

Two such gates are exercised here. Fitting a model run refuses to look at the
run's own four status dimensions until it has read the `status` of the data
window that will train it, so the same PENDING run is admissible or refused
purely on the strength of a row it does not own. Running the budget optimizer
reads further still: it consults the computed `data_posture` of the market,
which is itself an answer derived from the market's windows and runs, so a
single reopen two entities away is enough to turn a DRAFT scenario into a
refusal — and re-sealing that window is enough to turn it back.
"""

from typing import Any, Dict

from test_helpers import ApiClient, validate_error, validate_paginated, validate_success
from test_helpers import assertions as expect
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId

# The instant at which the second canonical window, [2026-09-01, 2026-09-29),
# has elapsed and may therefore be sealed.
_CLOCK_SECOND_WINDOW_ELAPSED = "2026-09-29T00:00:00Z"


def _contribution_rows(api: ApiClient, run_id: str) -> tuple:
    """Every decomposition row of one run, with the page meta that framed it."""
    return validate_paginated(
        api.list_channel_contributions(users.MODELER, {"model_run_id": run_id})
    )


def _second_window_sealed(api: ApiClient, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """A second complete window of the same market, carried through to SEALED.

    It is filed against the four September periods so that it neither collides
    with the canonical August window nor shares any sales period with it, and it
    is sealed once the clock has passed its exclusive end.
    """
    window = fx.create_data_window(
        api,
        ctx["market"]["id"],
        window_start_date=f.SECOND_WINDOW_START,
        window_end_date=f.SECOND_WINDOW_END,
    )
    fx.file_sales_rows(api, window["id"], periods=f.SECOND_WINDOW_PERIODS)
    fx.file_spend_chain(
        api,
        window["id"],
        fx.f1_spend_entries(
            ctx["a_search"]["id"],
            ctx["b_social"]["id"],
            periods=f.SECOND_WINDOW_PERIODS,
        ),
    )
    fx.set_clock(api, _CLOCK_SECOND_WINDOW_ELAPSED)
    return validate_success(api.seal_data_window(window["id"], users.DATA_ENGINEER))


def _reopen(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Reopen a sealed window, which is what drives the market into FROZEN."""
    return validate_success(
        api.reopen_data_window(window_id, f.reopen_payload(), users.DATA_ENGINEER)
    )


def test_fit_refused_while_the_training_window_is_still_open(api):
    """PRD §3.4: "The training window must be in `SEALED` status; a run whose
    window is `OPEN` or `REOPENED` is refused with `ERR_DATA_WINDOW_NOT_SEALED`."

    The run itself is faultless: PRD §3.4 says "A newly created run reports
    `fit_status` `PENDING`, `validation_status` `UNVALIDATED`,
    `calibration_status` `NOT_REQUIRED` and `publication_status` `UNPUBLISHED`."
    Only the window's status stands in the way, and no decomposition row is
    written.

    Design: Difficulty/cross_entity_state_dependency/model_run_fit_requires_sealed_data_window
    """
    ctx = fx.window_with_observations(api)
    assert ctx["window"]["status"] == "OPEN"
    run = fx.create_run(api, ctx)
    expect.assert_run_state(run, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED")

    response = api.fit_model_run(run["id"], users.MODELER)
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_NOT_SEALED.value, 409)

    after = validate_success(api.get_model_run(run["id"], users.MODELER))
    expect.assert_run_state(
        after, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    expect.assert_version_unchanged(run, after)

    rows, meta = _contribution_rows(api, run["id"])
    assert rows == []
    assert meta["total_count"] == 0


def test_fit_refused_while_the_training_window_is_reopened(api):
    """PRD §3.4: "The training window must be in `SEALED` status; a run whose
    window is `OPEN` or `REOPENED` is refused with `ERR_DATA_WINDOW_NOT_SEALED`."

    `REOPENED` is the second half of that disjunction, and PRD §3.3 explains why
    the window can get there: "The transition sets `status` to `REOPENED`,
    increases `reopen_count` by one, and bumps `version`." The run was declared
    while the window was sealed and has never been fitted, so nothing about it
    changed; only the window moved underneath it.

    Design: Difficulty/cross_entity_state_dependency/model_run_fit_requires_sealed_data_window
    """
    ctx = fx.sealed_window(api)
    run = fx.create_run(api, ctx)
    reopened = _reopen(api, ctx["window"]["id"])
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1

    response = api.fit_model_run(run["id"], users.MODELER)
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_NOT_SEALED.value, 409)

    after = validate_success(api.get_model_run(run["id"], users.MODELER))
    expect.assert_run_state(
        after, "PENDING", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    expect.assert_version_unchanged(run, after)

    rows, meta = _contribution_rows(api, run["id"])
    assert rows == []
    assert meta["total_count"] == 0


def test_fit_admitted_once_the_training_window_is_sealed(api):
    """PRD §3.4: "Fitting is the `Modeler`'s core operation and it moves
    `fit_status` from `PENDING` to `FITTED`, or from `STALE_FIT` back to
    `FITTED`."

    The identical run declaration that the previous cases refused is admitted
    here on the strength of the window alone. PRD §3.4: "A successful fit writes
    one decomposition row per included channel, created in ascending
    `channel_code` order, each with `is_current` true and with
    `calibrated_contribution_units` and `calibrated_contribution_revenue_cents`
    initially equal to their uncalibrated counterparts — that equality holds for
    as long as the run's `calibration_status` remains `NOT_REQUIRED` or
    `PENDING_CALIBRATION`." And: "The run then sets `fit_status` to `FITTED`,
    resets `validation_status` to `UNVALIDATED`, clears `holdout_mape_pct` to
    null, records the acting operator in `fitted_by_user_id`, and increments its
    `version`."

    Design: Difficulty/cross_entity_state_dependency/model_run_fit_requires_sealed_data_window
    """
    ctx = fx.sealed_window(api)
    assert ctx["window"]["status"] == "SEALED"
    run = fx.create_run(api, ctx)

    fitted = validate_success(api.fit_model_run(run["id"], users.MODELER))
    expect.assert_run_state(
        fitted, "FITTED", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    assert fitted["holdout_mape_pct"] is None
    assert fitted["fitted_by_user_id"] == users.MODELER_ID
    assert fitted["version"] == run["version"] + 1

    # PRD §3.4: the three run-level aggregates are taken over every sales
    # observation of the window, holdout periods included.
    assert fitted["observation_period_count"] == fx.F1_OBSERVATION_PERIOD_COUNT
    assert fitted["modeled_sales_units"] == fx.F1_MODELED_SALES_UNITS
    assert fitted["unit_price_cents"] == fx.F1_UNIT_PRICE_CENTS
    assert fitted["baseline_sales_units"] == fx.F1_EFFECT_BASELINE_UNITS

    rows, meta = _contribution_rows(api, run["id"])
    assert meta["total_count"] == 2
    by_channel = expect.rows_by(rows, "channel_id")
    a_search = by_channel[ctx["a_search"]["id"]]
    b_social = by_channel[ctx["b_social"]["id"]]
    assert a_search["contribution_units"] == fx.F1_EFFECT_CONTRIBUTION_A_SEARCH
    assert b_social["contribution_units"] == fx.F1_EFFECT_CONTRIBUTION_B_SOCIAL
    for row in (a_search, b_social):
        assert row["is_current"] is True
        assert row["calibrated_contribution_units"] == row["contribution_units"]
        assert (
            row["calibrated_contribution_revenue_cents"]
            == row["contribution_revenue_cents"]
        )
    expect.assert_baseline_identity(fitted, rows)


def test_refit_of_a_stale_run_refused_while_its_window_stays_reopened(api):
    """PRD §3.3: "The first hop reaches the runs: every model run whose training
    window is this one and whose `fit_status` is `FITTED` moves to `fit_status`
    `STALE_FIT` and simultaneously has its `validation_status` reset to
    `UNVALIDATED`, because a backtest against retracted data proves nothing."

    A `STALE_FIT` run is the one shape the fit endpoint would otherwise accept,
    yet PRD §3.4 still refuses it: "The training window must be in `SEALED`
    status; a run whose window is `OPEN` or `REOPENED` is refused with
    `ERR_DATA_WINDOW_NOT_SEALED`." Its stale decomposition survives the refusal,
    because PRD §3.3 also says "The second hop, caused by the first, reaches
    those runs' decomposition rows: every `ChannelContribution` row belonging to
    each affected run has `is_current` set to false."

    Design: Difficulty/cross_entity_state_dependency/model_run_fit_requires_sealed_data_window
    """
    ctx = fx.fitted_run(api)
    run_id = ctx["run"]["id"]
    _reopen(api, ctx["window"]["id"])

    stale = validate_success(api.get_model_run(run_id, users.MODELER))
    expect.assert_run_state(
        stale, "STALE_FIT", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    before_rows, before_meta = _contribution_rows(api, run_id)
    assert before_meta["total_count"] == 2
    assert [row["is_current"] for row in before_rows] == [False, False]

    response = api.fit_model_run(run_id, users.MODELER)
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_NOT_SEALED.value, 409)

    after = validate_success(api.get_model_run(run_id, users.MODELER))
    expect.assert_run_state(
        after, "STALE_FIT", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    expect.assert_version_unchanged(stale, after)
    expect.assert_same_row(
        stale,
        after,
        "modeled_sales_units",
        "unit_price_cents",
        "baseline_sales_units",
        "fitted_by_user_id",
    )

    after_rows, after_meta = _contribution_rows(api, run_id)
    assert after_meta["total_count"] == 2
    assert [row["is_current"] for row in after_rows] == [False, False]
    assert [row["id"] for row in after_rows] == [row["id"] for row in before_rows]


def test_optimize_refused_when_a_reopened_window_freezes_the_market_posture(api):
    """PRD §2.8: "Locking an experiment design, publishing a model run and filing
    a reconciliation report all require that the posture is not `FROZEN`; running
    the budget optimizer requires the stricter condition that the posture is
    exactly `OPEN`."

    The posture is not a field a planner can set. PRD §2.8: "First: if any data
    window belonging to the market is in `REOPENED` status, the posture is
    `FROZEN`." So reopening a window that this scenario never referenced is
    enough, and PRD §3.3 says the draft itself is left alone: "Scenarios in
    `DRAFT` are deliberately untouched by that fourth hop — a draft holds no
    optimizer output to unwind, so it stays writable, and it is the scenario's
    own later optimize attempt that surfaces `ERR_MARKET_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/budget_scenario_optimize_requires_open_market_posture
    """
    ctx = fx.scenario_with_allocations(api)
    assert ctx["market"]["data_posture"] == "OPEN"
    assert ctx["scenario"]["status"] == "DRAFT"

    second = _second_window_sealed(api, ctx)
    assert fx.refresh_market(api, ctx)["data_posture"] == "OPEN"
    _reopen(api, second["id"])
    assert fx.refresh_market(api, ctx)["data_posture"] == "FROZEN"

    before = fx.refresh_scenario(api, ctx)
    response = api.optimize_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER)
    validate_error(response, ApiErrorId.ERR_MARKET_POSTURE_BLOCKED.value, 409)

    after = fx.refresh_scenario(api, ctx)
    assert after["status"] == "DRAFT"
    expect.assert_version_unchanged(before, after)
    expect.assert_same_row(
        before,
        after,
        "reallocation_fee_cents",
        "allocated_total_cents",
        "unallocated_cents",
        "shifted_total_cents",
        "projected_contribution_units",
        "projected_incremental_revenue_cents",
    )
    # PRD §3.8: the conservation identity "holds in every response thereafter".
    expect.assert_budget_conservation(after)

    # PRD §3.8: "A new row starts with `allocated_cents` equal to its
    # `baseline_spend_cents`, `shifted_cents` 0, `constraint_binding` `NONE` and
    # `projected_contribution_units` 0.0000".
    for row in fx.allocations_of(api, ctx["scenario"]["id"]):
        assert row["allocated_cents"] == row["baseline_spend_cents"]
        assert row["shifted_cents"] == 0
        assert row["constraint_binding"] == "NONE"
        assert row["projected_contribution_units"] == 0.0


def test_optimize_admitted_once_resealing_returns_the_posture_to_open(api):
    """PRD §3.3: "Sealing sets `status` to `SEALED`, bumps the window's `version`,
    and recomputes the market's posture."

    Re-sealing the reopened window removes the only reason the market was
    `FROZEN`, and PRD §2.8 then lands on the last rung of its ordered test:
    "Otherwise the posture is `OPEN`." The very request that was refused a moment
    ago now succeeds, and PRD §3.8 says what it must report: "The scenario moves
    to `OPTIMIZED` and its `version` increments, and the identity that
    `allocated_total_cents` plus `reallocation_fee_cents` plus
    `unallocated_cents` equals `total_budget_cents` is directly checkable off the
    response."

    Design: Difficulty/cross_entity_state_dependency/budget_scenario_optimize_requires_open_market_posture
    """
    ctx = fx.scenario_with_allocations(api)
    second = _second_window_sealed(api, ctx)
    _reopen(api, second["id"])
    assert fx.refresh_market(api, ctx)["data_posture"] == "FROZEN"
    blocked = api.optimize_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER)
    validate_error(blocked, ApiErrorId.ERR_MARKET_POSTURE_BLOCKED.value, 409)

    resealed = validate_success(api.seal_data_window(second["id"], users.DATA_ENGINEER))
    assert resealed["status"] == "SEALED"
    assert fx.refresh_market(api, ctx)["data_posture"] == "OPEN"

    draft = fx.refresh_scenario(api, ctx)
    assert draft["status"] == "DRAFT"
    optimized = validate_success(
        api.optimize_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER)
    )
    assert optimized["status"] == "OPTIMIZED"
    assert optimized["version"] == draft["version"] + 1
    assert optimized["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS
    assert optimized["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS
    assert optimized["shifted_total_cents"] == fx.F1_SHIFTED_TOTAL_CENTS
    assert optimized["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS
    assert optimized["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_TOTAL
    assert (
        optimized["projected_incremental_revenue_cents"]
        == fx.F1_PROJECTED_REVENUE_CENTS
    )
    expect.assert_budget_conservation(optimized)

    by_channel = expect.rows_by(
        fx.allocations_of(api, ctx["scenario"]["id"]), "channel_id"
    )
    a_search = by_channel[ctx["a_search"]["id"]]
    b_social = by_channel[ctx["b_social"]["id"]]
    assert a_search["allocated_cents"] == fx.F1_ALLOCATED_A_SEARCH_CENTS
    assert b_social["allocated_cents"] == fx.F1_ALLOCATED_B_SOCIAL_CENTS
    assert a_search["shifted_cents"] == fx.F1_SHIFTED_A_SEARCH_CENTS
    assert b_social["shifted_cents"] == fx.F1_SHIFTED_B_SOCIAL_CENTS
    assert a_search["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_A_SEARCH
    assert b_social["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_B_SOCIAL
