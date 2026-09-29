"""Every write is visible in its own response and in the very next read.

The contract allows no settling time anywhere: a mutation's own response body
already carries every field it derived, and the aggregate it moved on a
different entity is correct on the first following read. Both cases below are
therefore written as a single mutation followed by exactly one read — never a
retry, never a second attempt — so an implementation that recomputed counters
lazily on some later request would be caught immediately.
"""

from decimal import Decimal
from typing import Any, Dict

from test_helpers import (
    ApiClient,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# The two equal-sized cells the geographic design enlists.
_CELL_POPULATION = 100_000
_HELD_OUT_POPULATION = 200_000
_HELD_OUT_POPULATION_PCT = 2.00

# Planned arms large enough to clear the power gate on their own.
_PLANNED_ARM_POPULATION = 500_000

# The first weekly sales row of the window, and what it leaves behind.
_FIRST_PERIOD_AVG_PRICE_CENTS = 5000
_ONE_PERIOD_SALES_COUNT = 1
_ONE_PERIOD_LAG_COMPLETENESS_PCT = 25.00
_WINDOW_VERSION_AFTER_FIRST_SALES = 2


def _num(value: Any) -> Decimal:
    """A decimal-valued field, compared at its stated scale rather than in binary."""
    return Decimal(str(value))


def _fixture(api: ApiClient) -> Dict[str, Any]:
    """One market, two cells, an empty open window and a locked geo design."""
    ctx = fx.market_with_channels(api)
    ctx["cells"] = fx.create_geo_cells(
        api,
        ctx["market"]["id"],
        [("GC01", _CELL_POPULATION), ("GC02", _CELL_POPULATION)],
    )
    ctx["window"] = fx.create_data_window(api, ctx["market"]["id"])
    assert ctx["window"]["status"] == "OPEN"
    assert ctx["window"]["sales_period_count"] == 0
    assert ctx["window"]["spend_observation_count"] == 0
    fx.set_clock(api, f.WINDOW_START)
    ctx["experiment"] = fx.locked_experiment(
        api, ctx, geo=True, planned_population=_PLANNED_ARM_POPULATION
    )
    assert ctx["experiment"]["status"] == "DESIGN_LOCKED"
    return ctx


def test_sales_write_carries_its_own_derived_field_and_moves_the_window_at_once(
    api: ApiClient,
):
    """PRD 2.10: "Cascades are immediate and synchronous; there is no deferred
    sweep and no eventual consistency."
    PRD 3.2: "On acceptance the row's `avg_price_cents` is computed as
    `revenue_cents` divided by `units_sold`, rounded half-up to a whole cent; it is
    reporting only."
    PRD 3.2: "The parent window then increases its `sales_period_count` by one and
    recomputes `lag_completeness_pct` as one hundred multiplied by
    `sales_period_count`, divided by `expected_period_count`, rounded half-up to
    two decimal places — which, because each period admits at most one sales row,
    is exactly the share of the window's expected periods that carry a sales
    observation."
    PRD 3.2: "The window's `version` is incremented."

    Design: Corner/consistency_model/every_write_is_visible_in_the_same_response_and_the_next_read
    """
    ctx = _fixture(api)
    row = f.F1_SALES_ROWS[0]

    created = validate_success(
        api.create_sales_observation(
            f.sales_observation_payload(
                ctx["window"]["id"],
                f.WINDOW_PERIODS[0],
                row["units_sold"],
                row["revenue_cents"],
            ),
            users.DATA_ENGINEER,
        ),
        201,
    )
    # The create response itself already carries the derived cent figure.
    assert created["avg_price_cents"] == _FIRST_PERIOD_AVG_PRICE_CENTS

    # This is the FIRST read of the parent after that write, with no retry.
    window = validate_success(
        api.get_data_window(ctx["window"]["id"], users.AUDITOR)
    )
    assert window["sales_period_count"] == _ONE_PERIOD_SALES_COUNT
    assert _num(window["lag_completeness_pct"]) == _num(
        _ONE_PERIOD_LAG_COMPLETENESS_PCT
    )
    assert window["version"] == _WINDOW_VERSION_AFTER_FIRST_SALES


def test_cell_assignment_is_visible_on_the_experiment_market_and_filtered_index(
    api: ApiClient,
):
    """PRD 2.10: "Cascades are immediate and synchronous; there is no deferred
    sweep and no eventual consistency."
    PRD 3.6: "The experiment's `treatment_population` becomes the summed population
    of its treatment cells and its `control_population` the summed population of its
    control cells."
    PRD 3.6: "On success, each cell named in `treatment_cell_ids` moves to
    `assignment_state` `TREATMENT` and each cell named in `control_cell_ids` moves
    to `CONTROL`, both recording the experiment in their `assigned_experiment_id`;
    each such cell adds its `population` to the market's `held_out_population`."
    PRD 3.1: "Alongside it, `held_out_population_pct` is reported as one hundred
    multiplied by `held_out_population`, divided by `total_population`, rounded
    half-up to two decimal places; this percentage is for human reporting only and
    is never the quantity a holdout-share rule compares against."
    PRD 3.1: "Cells can be listed filtered by `market_id`, by `assignment_state`, by
    `cell_code`, or by `assigned_experiment_id` — the last of which is the only way
    to discover which cells a given experiment consumed, since cell assignment
    happens as a cascade rather than through a per-cell write."

    Design: Corner/consistency_model/every_write_is_visible_in_the_same_response_and_the_next_read
    """
    ctx = _fixture(api)
    treatment_cell, control_cell = ctx["cells"]

    assigned = validate_success(
        api.assign_cells(
            ctx["experiment"]["id"],
            f.assign_cells_payload([treatment_cell["id"]], [control_cell["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )
    # The realised arm populations are already on the mutation's own body.
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == _CELL_POPULATION
    assert assigned["control_population"] == _CELL_POPULATION

    # First read of the market after the cascade, with no settle delay.
    market = validate_success(api.get_market(ctx["market"]["id"], users.AUDITOR))
    assert market["held_out_population"] == _HELD_OUT_POPULATION
    assert _num(market["held_out_population_pct"]) == _num(_HELD_OUT_POPULATION_PCT)

    # First read of the filtered cell index, which is consistent immediately too.
    rows, meta = validate_paginated(
        api.list_geo_cells(
            users.AUDITOR,
            {
                "market_id": ctx["market"]["id"],
                "assignment_state": "TREATMENT",
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == treatment_cell["id"]
    assert rows[0]["assignment_state"] == "TREATMENT"
    assert rows[0]["assigned_experiment_id"] == ctx["experiment"]["id"]
