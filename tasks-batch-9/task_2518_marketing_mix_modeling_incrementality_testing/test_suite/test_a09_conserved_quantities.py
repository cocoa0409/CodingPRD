"""The two quantities the contract conserves, each broken and then restored.

The fiscal quantity lives on a budget scenario: three cent buckets that always
add up to the whole budget. The optimizer redistributes them and reverting the
optimization is the exact compensating action, so the same scenario can be walked
around the cycle and must land field-for-field where it started. The population
quantity lives on a market: the people its geographic cells hold out of
measurement. Enlisting cells breaks it away from zero, and releasing the cells is
deliberately *not* the compensating action — a released cell is still quarantined
— so only the market washout sweep, and only once the quarantine has elapsed,
gives the population back.
"""

from typing import Any, Dict, List

from test_helpers import ApiClient, validate_success
from test_helpers import assertions as expect
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# Two twin cells that between them sit exactly on the market's holdout ceiling.
_CELL_SPECS = [
    ("GC01", fx.F1_CEILING_CELL_POPULATION),
    ("GC02", fx.F1_CEILING_CELL_POPULATION),
]

# The arms of the geographic design, one twin cell each.
_GEO_ARM_POPULATION = fx.F1_CEILING_CELL_POPULATION

# Both twins held out of a ten-million-person market is twenty percent of it.
_HELD_OUT_PCT_WHILE_QUARANTINED = 20.00


def _cells_of(api: ApiClient, market_id: str) -> List[Dict[str, Any]]:
    """Every geographic cell of one market, freshly read."""
    return validate_success(
        api.list_geo_cells(users.EXPERIMENT_DESIGNER, {"market_id": market_id})
    )


def _market_now(api: ApiClient, market_id: str) -> Dict[str, Any]:
    """The market row as it stands, for reading its two population aggregates."""
    return validate_success(api.get_market(market_id, users.EXPERIMENT_DESIGNER))


def _rejected_geo_experiment(api: ApiClient) -> Dict[str, Any]:
    """A market whose two cells are enlisted into a design that was rejected.

    The design is carried right through the lifecycle so that the population is
    genuinely broken away from zero before the release step is examined.
    """
    ctx = fx.market_with_channels(api)
    ctx["cells"] = fx.create_geo_cells(api, ctx["market"]["id"], _CELL_SPECS)
    treatment, control = ctx["cells"]
    ctx["experiment"] = fx.rejected_experiment(
        api,
        ctx,
        geo=True,
        planned_population=_GEO_ARM_POPULATION,
        treatment_cell_ids=[treatment["id"]],
        control_cell_ids=[control["id"]],
    )
    assert ctx["experiment"]["status"] == "REJECTED"
    return ctx


def test_optimizer_redistributes_the_three_cent_buckets_without_losing_a_cent(api):
    """PRD §2.10: "The first is fiscal: for every budget scenario, the sum of
    `allocated_total_cents`, `reallocation_fee_cents` and `unallocated_cents`
    equals `total_budget_cents` at every observable moment."

    This is the operation that breaks the trivial split, because PRD §2.10 goes on:
    "The optimizer is what redistributes those three components, and reverting an
    optimization restores them to their pre-optimization values with no residual
    drift." The fee that carves the first slice is priced once, since PRD §3.8 says
    "The pass-one churn is the sum, across channels, of the absolute difference
    between each channel's pass-one allocation and its `baseline_spend_cents`, and
    `reallocation_fee_cents` is that churn multiplied by `reallocation_fee_pct`,
    divided by one hundred, rounded half-up to a whole cent."

    Design: Difficulty/compensating_invariant/budget_cent_conservation_restored_by_revert_optimization
    """
    ctx = fx.scenario_with_allocations(api)
    # PRD §3.8: at creation "those three cent totals are trivially zero at that
    # moment; the conservation identity of §2.10 becomes meaningful as soon as rows
    # exist and holds in every response thereafter" — so the identity is checked on
    # the scenario as it reads now that its allocation rows exist, not on the
    # creation snapshot the fixture happens to have kept.
    draft = fx.refresh_scenario(api, ctx)
    assert draft["status"] == "DRAFT"
    assert draft["total_budget_cents"] == f.SCENARIO_TOTAL_BUDGET_CENTS
    expect.assert_budget_conservation(draft)

    optimized = validate_success(
        api.optimize_budget_scenario(draft["id"], users.BRAND_PLANNER)
    )
    assert optimized["status"] == "OPTIMIZED"
    # PRD §3.8: "The scenario moves to `OPTIMIZED` and its `version` increments" —
    # one past whatever the version read immediately before the optimize call.
    assert optimized["version"] == draft["version"] + 1

    # The fee prices the plan pass one proposed, not the smaller pass-two churn.
    assert optimized["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS
    assert optimized["reallocation_fee_cents"] != fx.F1_FORBIDDEN_RECOMPUTED_FEE_CENTS

    assert optimized["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS
    assert optimized["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS
    assert optimized["shifted_total_cents"] == fx.F1_SHIFTED_TOTAL_CENTS
    assert optimized["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_TOTAL
    assert (
        optimized["projected_incremental_revenue_cents"]
        == fx.F1_PROJECTED_REVENUE_CENTS
    )
    expect.assert_budget_conservation(optimized)

    by_channel = expect.rows_by(fx.allocations_of(api, draft["id"]), "channel_id")
    a_search = by_channel[ctx["a_search"]["id"]]
    b_social = by_channel[ctx["b_social"]["id"]]
    assert a_search["allocated_cents"] == fx.F1_ALLOCATED_A_SEARCH_CENTS
    assert b_social["allocated_cents"] == fx.F1_ALLOCATED_B_SOCIAL_CENTS
    assert a_search["shifted_cents"] == fx.F1_SHIFTED_A_SEARCH_CENTS
    assert b_social["shifted_cents"] == fx.F1_SHIFTED_B_SOCIAL_CENTS
    assert a_search["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_A_SEARCH
    assert b_social["projected_contribution_units"] == fx.F1_PROJECTED_UNITS_B_SOCIAL
    # PRD §3.8: allocated_total_cents is the sum of the rows' allocated_cents and
    # shifted_total_cents the sum of their shifted_cents.
    assert (
        a_search["allocated_cents"] + b_social["allocated_cents"]
        == optimized["allocated_total_cents"]
    )
    assert (
        a_search["shifted_cents"] + b_social["shifted_cents"]
        == optimized["shifted_total_cents"]
    )


def test_revert_optimization_restores_every_bucket_and_every_row_exactly(api):
    """PRD §3.8: "It restores every allocation row to `allocated_cents` equal to
    `baseline_spend_cents`, `shifted_cents` 0, `constraint_binding` `NONE` and
    `projected_contribution_units` 0.0000; on the scenario it sets
    `reallocation_fee_cents`, `shifted_total_cents`, `unallocated_cents` and
    `projected_incremental_revenue_cents` to 0, `projected_contribution_units` to
    0.0000, and `allocated_total_cents` to `total_budget_cents`; and it returns the
    scenario to `DRAFT` with its `version` incremented."

    That is the compensating half of the fiscal quantity, and PRD §3.8 states the
    standard it is held to: "Every side effect of the optimizer is undone with no
    residual drift, and the conservation identity still holds afterwards."

    Design: Difficulty/compensating_invariant/budget_cent_conservation_restored_by_revert_optimization
    """
    ctx = fx.optimized_scenario(api)
    optimized = ctx["scenario"]
    assert optimized["status"] == "OPTIMIZED"
    assert optimized["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS

    reverted = validate_success(
        api.revert_optimization(optimized["id"], users.BRAND_PLANNER)
    )
    assert reverted["status"] == "DRAFT"
    assert reverted["version"] == optimized["version"] + 1
    assert reverted["reallocation_fee_cents"] == 0
    assert reverted["shifted_total_cents"] == 0
    assert reverted["unallocated_cents"] == 0
    assert reverted["projected_incremental_revenue_cents"] == 0
    assert reverted["projected_contribution_units"] == 0.0
    assert reverted["allocated_total_cents"] == reverted["total_budget_cents"]
    assert reverted["total_budget_cents"] == f.SCENARIO_TOTAL_BUDGET_CENTS
    expect.assert_budget_conservation(reverted)

    rows = fx.allocations_of(api, optimized["id"])
    assert len(rows) == 2
    for row in rows:
        assert row["allocated_cents"] == row["baseline_spend_cents"]
        assert row["shifted_cents"] == 0
        assert row["constraint_binding"] == "NONE"
        assert row["projected_contribution_units"] == 0.0

    by_channel = expect.rows_by(rows, "channel_id")
    assert (
        by_channel[ctx["a_search"]["id"]]["baseline_spend_cents"]
        == f.BASELINE_A_SEARCH_CENTS
    )
    assert (
        by_channel[ctx["b_social"]["id"]]["baseline_spend_cents"]
        == f.BASELINE_B_SOCIAL_CENTS
    )
    assert (
        sum(row["allocated_cents"] for row in rows)
        == reverted["allocated_total_cents"]
    )


def test_optimize_revert_optimize_lands_on_identical_figures(api):
    """PRD §3.8: "The `DRAFT` and `OPTIMIZED` states therefore form a cycle a
    planner can walk as many times as it likes."

    A compensating action that leaves residue would show up on the second lap, so
    the second optimization is compared field-for-field against the first. PRD §3.8:
    "Every side effect of the optimizer is undone with no residual drift, and the
    conservation identity still holds afterwards."

    Design: Difficulty/compensating_invariant/budget_cent_conservation_restored_by_revert_optimization
    """
    ctx = fx.optimized_scenario(api)
    first = ctx["scenario"]
    first_rows = expect.rows_by(fx.allocations_of(api, first["id"]), "channel_id")

    validate_success(api.revert_optimization(first["id"], users.BRAND_PLANNER))
    second = validate_success(
        api.optimize_budget_scenario(first["id"], users.BRAND_PLANNER)
    )
    assert second["status"] == "OPTIMIZED"
    expect.assert_same_row(
        first,
        second,
        "total_budget_cents",
        "reallocation_fee_pct",
        "reallocation_fee_cents",
        "allocated_total_cents",
        "shifted_total_cents",
        "unallocated_cents",
        "projected_contribution_units",
        "projected_incremental_revenue_cents",
    )
    expect.assert_budget_conservation(second)

    second_rows = expect.rows_by(fx.allocations_of(api, first["id"]), "channel_id")
    assert set(second_rows) == set(first_rows)
    for channel_id, before in first_rows.items():
        expect.assert_same_row(
            before,
            second_rows[channel_id],
            "id",
            "baseline_spend_cents",
            "allocated_cents",
            "shifted_cents",
            "constraint_binding",
            "projected_contribution_units",
        )


def test_release_cells_moves_the_arms_to_washout_without_giving_the_people_back(api):
    """PRD §2.10: "Enlisting cells into an experiment is what breaks the quantity
    away from zero; releasing an experiment's cells alone does not restore it,
    because a released cell sits in `WASHOUT` and is still held out."

    PRD §3.6 spells out what the release does do: "In both cases every geographic
    cell whose `assigned_experiment_id` is this experiment and whose
    `assignment_state` is `TREATMENT` or `CONTROL` moves to `WASHOUT`, with
    `washout_until_date` set to the experiment's `end_date` advanced by its
    `washout_days` days." Meanwhile PRD §3.6 also says of the redesign loop that it
    "increments `redesign_count`, clears `computed_power` and `power_index` back to
    null, clears all four conversion counts and all four lift fields —
    `measured_lift_pct`, `lift_ci_half_width_pct`, `lift_ci_low_pct` and
    `lift_ci_high_pct` — back to null, resets `treatment_population` and
    `control_population` to 0, and increments `version`."

    Design: Difficulty/compensating_invariant/holdout_population_conservation_restored_by_release_then_sweep
    """
    ctx = _rejected_geo_experiment(api)
    market_id = ctx["market"]["id"]
    experiment = ctx["experiment"]

    enlisted = _market_now(api, market_id)
    assert enlisted["held_out_population"] == fx.F1_HOLDOUT_CEILING_POPULATION
    assert enlisted["held_out_population_pct"] == _HELD_OUT_PCT_WHILE_QUARANTINED
    expect.assert_holdout_conservation(enlisted, _cells_of(api, market_id))
    expect.assert_celled_population(enlisted, _cells_of(api, market_id))

    released = validate_success(
        api.release_cells(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert released["status"] == "DRAFT"
    assert released["redesign_count"] == experiment["redesign_count"] + 1
    assert released["version"] == experiment["version"] + 1
    expect.assert_draft_experiment_fields_cleared(released)

    cells = _cells_of(api, market_id)
    assert len(cells) == 2
    for cell in cells:
        assert cell["assignment_state"] == "WASHOUT"
        assert cell["assigned_experiment_id"] == experiment["id"]
        # end_date 2026-10-05 advanced by the design's seven washout days.
        assert cell["washout_until_date"] is not None
        assert cell["washout_until_date"].startswith("2026-10-12")

    after = _market_now(api, market_id)
    assert after["held_out_population"] == fx.F1_HOLDOUT_CEILING_POPULATION
    assert after["held_out_population_pct"] == _HELD_OUT_PCT_WHILE_QUARANTINED
    expect.assert_holdout_conservation(after, cells)
    expect.assert_celled_population(after, cells)


def test_sweep_before_the_quarantine_elapses_changes_nothing_and_is_no_error(api):
    """PRD §3.1: "Cells whose quarantine has not yet elapsed are skipped silently:
    they are left exactly as they were and their presence is not an error, so one
    sweep call routinely applies to some cells and not others."

    Both cells are quarantined until 2026-10-12, and the clock is one day short of
    that, so the sweep must succeed and hand nothing back. PRD §2.10: "Only the
    market washout sweep gives the population back."

    Design: Difficulty/compensating_invariant/holdout_population_conservation_restored_by_release_then_sweep
    """
    ctx = _rejected_geo_experiment(api)
    market_id = ctx["market"]["id"]
    validate_success(
        api.release_cells(ctx["experiment"]["id"], users.EXPERIMENT_DESIGNER)
    )
    before_cells = _cells_of(api, market_id)
    before_market = _market_now(api, market_id)

    fx.set_clock(api, fx.CLOCK_BEFORE_WASHOUT_ELAPSED, users.EXPERIMENT_DESIGNER)
    validate_success(api.washout_sweep(market_id, users.EXPERIMENT_DESIGNER))

    after_cells = expect.rows_by(_cells_of(api, market_id), "cell_code")
    for before in before_cells:
        expect.assert_same_row(
            before,
            after_cells[before["cell_code"]],
            "assignment_state",
            "assigned_experiment_id",
            "washout_until_date",
            "population",
            "version",
        )
        assert after_cells[before["cell_code"]]["assignment_state"] == "WASHOUT"

    after_market = _market_now(api, market_id)
    assert after_market["held_out_population"] == fx.F1_HOLDOUT_CEILING_POPULATION
    assert after_market["held_out_population_pct"] == _HELD_OUT_PCT_WHILE_QUARANTINED
    expect.assert_same_row(
        before_market,
        after_market,
        "held_out_population",
        "held_out_population_pct",
        "celled_population",
    )
    expect.assert_holdout_conservation(after_market, list(after_cells.values()))


def test_sweep_once_the_quarantine_elapses_returns_the_whole_population(api):
    """PRD §3.1: "It examines every cell of the market in `WASHOUT` and, for each
    one whose quarantine has elapsed — that is, whose `washout_until_date` is at or
    before the current logical clock — sets `assignment_state` back to
    `UNASSIGNED`, clears `assigned_experiment_id` to null, clears
    `washout_until_date` to null, and subtracts that cell's `population` from the
    market's `held_out_population`."

    The clock now reads exactly the quarantine deadline, which the rule counts as
    elapsed. PRD §3.1: "Afterwards the market's `held_out_population` and
    `held_out_population_pct` are recomputed and the market's `version` is
    incremented; when the last held cell clears, the two aggregates return to 0 and
    0.00 respectively." The cells themselves never left the market, because PRD §3.1
    says "`celled_population` is the summed `population` of every geographic cell
    belonging to the market, regardless of assignment."

    Design: Difficulty/compensating_invariant/holdout_population_conservation_restored_by_release_then_sweep
    """
    ctx = _rejected_geo_experiment(api)
    market_id = ctx["market"]["id"]
    validate_success(
        api.release_cells(ctx["experiment"]["id"], users.EXPERIMENT_DESIGNER)
    )
    before_market = _market_now(api, market_id)
    assert before_market["held_out_population"] == fx.F1_HOLDOUT_CEILING_POPULATION

    fx.set_clock(api, fx.CLOCK_WASHOUT_ELAPSED, users.EXPERIMENT_DESIGNER)
    validate_success(api.washout_sweep(market_id, users.EXPERIMENT_DESIGNER))

    cells = _cells_of(api, market_id)
    assert len(cells) == 2
    for cell in cells:
        assert cell["assignment_state"] == "UNASSIGNED"
        assert cell["assigned_experiment_id"] is None
        assert cell["washout_until_date"] is None
        assert cell["population"] == fx.F1_CEILING_CELL_POPULATION

    after_market = _market_now(api, market_id)
    assert after_market["held_out_population"] == 0
    assert after_market["held_out_population_pct"] == 0.00
    assert after_market["celled_population"] == fx.F1_HOLDOUT_CEILING_POPULATION
    assert after_market["version"] == before_market["version"] + 1
    expect.assert_holdout_conservation(after_market, cells)
    expect.assert_celled_population(after_market, cells)
