"""Input and state validation on the marketing-mix modelling service.

Each test here drives one validation rule of the contract to the exact point
where it either fires or deliberately does not, and always pairs a refusal with
a neighbouring call that succeeds, so a refusal cannot be explained by the
endpoint being unimplemented.

The harness relaunches the API against an empty database before every test, so
each test builds its whole precondition chain through the declared endpoints.
"""

from decimal import Decimal
from typing import Any, Dict, List, Tuple

from test_helpers import (
    ApiClient,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    test_users as users,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_SECOND_WINDOW_ELAPSED = "2026-09-29T00:00:00Z"
CLOCK_ONE_DAY_AFTER_START = "2026-09-08T00:00:00Z"


def _num(value: Any) -> Decimal:
    """A decimal answer compared exactly, whatever JSON type carries it."""
    return Decimal(str(value))


def _spend_entries(
    channel_id: str, periods: List[str], rows: List[Dict[str, int]]
) -> List[Tuple[str, str, Dict[str, int]]]:
    """One spend write per period for a single channel, in period order."""
    return [(channel_id, period, row) for period, row in zip(periods, rows)]


def _seal(api: ApiClient, window_id: str, clock: str) -> Dict[str, Any]:
    """Advance the clock past the window's exclusive end and seal it."""
    fx.set_clock(api, clock)
    return validate_success(api.seal_data_window(window_id, users.DATA_ENGINEER))


def _run_over(
    api: ApiClient, market_id: str, window_id: str, channel_ids: List[str]
) -> Dict[str, Any]:
    """Declare a run over one window; creation performs no fitting."""
    return validate_success(
        api.create_model_run(
            f.model_run_payload(market_id, window_id, channel_ids), users.MODELER
        ),
        201,
    )


def test_missing_spend_outranks_the_lag_window_shortfall_on_fit(
    api: ApiClient,
) -> None:
    """The missing-spend refusal wins when both fit gates are violated at once.

    "And every included channel must have at least one non-superseded spend
    observation inside the window, or `ERR_NO_SPEND_OBSERVATIONS`. When a single
    request violates both of the last two, the missing-spend failure is the one
    reported." The other gate is stated as: "The window's
    `expected_period_count` must be strictly greater than the largest
    `adstock_max_lag_periods` among the included channels — otherwise the
    declared lag structure cannot be identified from the data available — and a
    failure here is `ERR_LAG_WINDOW_INCOMPLETE`." And the ordering is named
    again in the worked example: "Fitting a run where an included channel has no
    usable spend observations *and* whose window is too short for the declared
    lag structure returns `ERR_NO_SPEND_OBSERVATIONS`, not
    `ERR_LAG_WINDOW_INCOMPLETE`."

    Both windows below hold four periods against a channel declaring four lag
    periods, so both violate the lag rule; only the first also lacks spend. The
    two fits therefore differ in exactly one input, which is what makes the
    ordering falsifiable rather than an artefact of one unimplemented rule.

    Design: Corner/validations/referential_beats_constraint_on_model_run_fit
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    channel = fx.create_channel(
        api,
        f.media_channel_payload(
            market["id"],
            channel_code="C_LAG",
            channel_type="VIDEO",
            adstock_max_lag_periods=4,
        ),
    )

    # W1 carries its four sales rows and no spend at all.
    first = fx.create_data_window(api, market["id"])
    fx.file_sales_rows(api, first["id"])
    _seal(api, first["id"], fx.CLOCK_WINDOW_ELAPSED)

    # W2 has the identical four-period shape plus the channel's four spend rows.
    second = fx.create_data_window(
        api,
        market["id"],
        window_start_date=f.SECOND_WINDOW_START,
        window_end_date=f.SECOND_WINDOW_END,
    )
    fx.file_sales_rows(api, second["id"], periods=f.SECOND_WINDOW_PERIODS)
    fx.file_spend_chain(
        api,
        second["id"],
        _spend_entries(
            channel["id"], f.SECOND_WINDOW_PERIODS, f.F1_SPEND_A_SEARCH
        ),
    )
    _seal(api, second["id"], CLOCK_SECOND_WINDOW_ELAPSED)

    run_without_spend = _run_over(
        api, market["id"], first["id"], [channel["id"]]
    )
    run_with_spend = _run_over(api, market["id"], second["id"], [channel["id"]])

    validate_error(
        api.fit_model_run(run_without_spend["id"], users.MODELER),
        ApiErrorId.ERR_NO_SPEND_OBSERVATIONS,
        422,
    )
    validate_error(
        api.fit_model_run(run_with_spend["id"], users.MODELER),
        ApiErrorId.ERR_LAG_WINDOW_INCOMPLETE,
        422,
    )

    for run in (run_without_spend, run_with_spend):
        after = validate_success(api.get_model_run(run["id"], users.MODELER))
        assert after["fit_status"] == "PENDING"
        assert after["version"] == 1
        rows, meta = validate_paginated(
            api.list_channel_contributions(
                users.MODELER, {"model_run_id": run["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


def test_period_placement_uses_the_half_open_range_and_conflict_the_closed_one(
    api: ApiClient,
) -> None:
    """The same date is an illegal period start and an occupied window endpoint.

    On placing an observation inside a window: "The supplied
    `period_start_date` has to fall inside the **half-open** range beginning at
    `window_start_date` and ending strictly before `window_end_date`, and it has
    to sit on the window's period grid: for a `WEEKLY` window that means an exact
    whole multiple of seven days after `window_start_date`, and for a `DAILY`
    window any day inside the range qualifies." And: "A date outside the
    half-open range or off the grid is `ERR_PERIOD_NOT_ALIGNED`."

    On placing a second window against the first: "The consequence is that two
    back-to-back windows whose endpoints merely touch do conflict: a window
    ending 2026-08-31 blocks a new window starting 2026-08-31, and the new window
    must start 2026-09-01 or later." Yet: "Granularity is part of the conflict
    key rather than a tie-break, so two windows of the same market with different
    granularities may overlap as freely as the analyst likes — a weekly window
    and a daily window over the same quarter are both legitimate views of the
    same period." And: "A genuine collision is `ERR_DATA_WINDOW_OVERLAP`."

    Design: Corner/validations/period_alignment_half_open_versus_closed_window_interval
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    channel = fx.create_channel(api, f.a_search_payload(market["id"]))
    window = fx.create_data_window(api, market["id"])
    version = fx.window_version(api, window["id"])

    # 2026-08-31 is the exclusive end, so it is not a period of the window.
    validate_error(
        api.create_sales_observation(
            f.sales_observation_payload(
                window["id"], f.WINDOW_END, 5000, 25000000
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_PERIOD_NOT_ALIGNED,
        422,
    )
    # 2026-08-05 is inside the range but off the weekly grid.
    validate_error(
        api.create_sales_observation(
            f.sales_observation_payload(
                window["id"], "2026-08-05T00:00:00Z", 5000, 25000000
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_PERIOD_NOT_ALIGNED,
        422,
    )
    # 2026-07-27 is on the grid extended backwards but before the range starts.
    validate_error(
        api.create_spend_observation(
            f.spend_observation_payload(
                window["id"],
                channel["id"],
                "2026-07-27T00:00:00Z",
                400000,
                version,
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_PERIOD_NOT_ALIGNED,
        422,
    )
    # 2026-08-24 is the last date the grid admits, and it is accepted.
    validate_success(
        api.create_spend_observation(
            f.spend_observation_payload(
                window["id"],
                channel["id"],
                f.WINDOW_PERIODS[3],
                500000,
                version,
            ),
            users.DATA_ENGINEER,
        ),
        201,
    )

    touching = {
        "market_id": market["id"],
        "window_start_date": f.WINDOW_END,
        "window_end_date": "2026-09-28T00:00:00Z",
    }
    validate_error(
        api.create_data_window(
            dict(touching, granularity="WEEKLY"), users.DATA_ENGINEER
        ),
        ApiErrorId.ERR_DATA_WINDOW_OVERLAP,
        409,
    )
    daily = validate_success(
        api.create_data_window(
            dict(touching, granularity="DAILY"), users.DATA_ENGINEER
        ),
        201,
    )
    assert daily["granularity"] == "DAILY"

    _, sales_meta = validate_paginated(
        api.list_sales_observations(
            users.DATA_ENGINEER, {"data_window_id": window["id"]}
        )
    )
    assert sales_meta["total_count"] == 0
    _, window_meta = validate_paginated(
        api.list_data_windows(users.DATA_ENGINEER, {"market_id": market["id"]})
    )
    assert window_meta["total_count"] == 2


def test_natural_keys_are_rejected_only_inside_the_scope_that_owns_them(
    api: ApiClient,
) -> None:
    """A duplicate key is refused inside its own scope and free outside it.

    "A second market claiming an existing `market_code` is rejected with
    `ERR_DUPLICATE_RESOURCE`." For channels: "A channel carries the `market_id`
    it belongs to and a `channel_code` following the same uppercase pattern as a
    market code — three to thirty-two characters, letter-initial — but required
    to be unique only within its market; a duplicate within one market is
    `ERR_DUPLICATE_RESOURCE`, while the same code in a different market is
    perfectly legal." For cells: "A cell's population is immutable once created —
    the whole holdout-share arithmetic depends on it being a stable denominator —
    and a repeated `cell_code` within a market is `ERR_DUPLICATE_RESOURCE`." And
    for sales: "**Sales** are filed at market level, one row per period, and
    here uniqueness *is* enforced: a period of a window may carry at most one
    sales row, and a second attempt is `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/scoped_duplicate_natural_keys_rejected
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    other_market = fx.create_second_market(api)
    fx.create_channel(api, f.a_search_payload(market["id"]))
    fx.create_geo_cell(api, market["id"], "GC01", 1_000_000)
    window = fx.create_data_window(api, market["id"])
    validate_success(
        api.create_sales_observation(
            f.sales_observation_payload(
                window["id"], f.WINDOW_PERIODS[0], 5000, 25000000
            ),
            users.DATA_ENGINEER,
        ),
        201,
    )
    before = validate_success(api.get_data_window(window["id"], users.DATA_ENGINEER))

    validate_error(
        api.create_market(
            f.market_payload(
                name="Duplicate Code Market",
                total_population=5_000_000,
                annual_budget_ceiling_cents=1_000_000_000,
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
        409,
    )
    validate_error(
        api.create_media_channel(
            f.media_channel_payload(
                market["id"],
                adstock_decay_rate=0.4,
                adstock_max_lag_periods=1,
                saturation_half_point_cents=100000,
                response_ceiling_units=900,
                min_spend_cents=100000,
                max_spend_cents=2000000,
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
        409,
    )
    validate_error(
        api.create_geo_cell(
            f.geo_cell_payload(market["id"], cell_code="GC01", population=50000),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
        409,
    )
    validate_error(
        api.create_sales_observation(
            f.sales_observation_payload(
                window["id"], f.WINDOW_PERIODS[0], 7000, 35000000
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
        409,
    )

    # The same two codes are free inside the second market.
    sibling_channel = validate_success(
        api.create_media_channel(
            f.a_search_payload(other_market["id"]), users.DATA_ENGINEER
        ),
        201,
    )
    assert sibling_channel["channel_code"] == "A_SEARCH"
    assert sibling_channel["market_id"] == other_market["id"]
    sibling_cell = validate_success(
        api.create_geo_cell(
            f.geo_cell_payload(
                other_market["id"], cell_code="GC01", population=400000
            ),
            users.DATA_ENGINEER,
        ),
        201,
    )
    assert sibling_cell["cell_code"] == "GC01"
    assert sibling_cell["market_id"] == other_market["id"]

    after = validate_success(api.get_data_window(window["id"], users.DATA_ENGINEER))
    assert after["sales_period_count"] == 1
    assert after["version"] == before["version"]


def test_holdout_ceiling_counts_the_market_wide_aggregate_at_lock_design(
    api: ApiClient,
) -> None:
    """The ceiling is checked against the whole market, not one design alone.

    "For a `GEO_HOLDOUT` design, the sum of the market's current
    `held_out_population`, the `planned_treatment_population` and the
    `planned_control_population`, multiplied by one hundred, must be at most
    twenty multiplied by the market's `total_population` — in other words the
    market may never plan to hold out more than twenty percent of its
    addressable people." And: "A breach is `ERR_HOLDOUT_SHARE_EXCEEDED`."

    The refused design would fit on its own; it breaches only once the cells a
    sibling already consumed are counted. Its refusal reserves nothing, because
    "A `DRAFT` sibling reserves nothing — it may never lock — and a `REJECTED` or
    `CLOSED` one has already given the channel back, so only locked-or-later
    experiments occupy time." A smaller design on the same channel over the same
    dates then locks: "A successful lock freezes `power_index` and
    `computed_power` onto the row, sets `status` to `DESIGN_LOCKED` and
    increments `version`." And: "A `GEO_HOLDOUT` design leaves both realised
    populations at 0 until it consumes actual cells."

    Design: Corner/validations/holdout_share_aggregate_across_two_experiments
    """
    ctx = fx.market_with_channels(api)
    cells = fx.create_geo_cells(
        api, ctx["market"]["id"], [("GC01", 500000), ("GC02", 500000)]
    )

    consuming = fx.create_experiment(api, ctx, geo=True, planned_population=500000)
    fx.locked_experiment(api, ctx, experiment=consuming)
    consuming = validate_success(
        api.assign_cells(
            consuming["id"],
            f.assign_cells_payload([cells[0]["id"]], [cells[1]["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )
    assert consuming["status"] == "CELLS_ASSIGNED"
    assert consuming["treatment_population"] == 500000
    assert consuming["control_population"] == 500000

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 1000000
    assert _num(market["held_out_population_pct"]) == Decimal("10.00")

    too_large = fx.create_experiment(
        api,
        ctx,
        channel_id=ctx["b_social"]["id"],
        geo=True,
        planned_population=700000,
    )
    fits = fx.create_experiment(
        api,
        ctx,
        channel_id=ctx["b_social"]["id"],
        geo=True,
        planned_population=400000,
    )

    validate_error(
        api.lock_design(too_large["id"], users.EXPERIMENT_DESIGNER),
        ApiErrorId.ERR_HOLDOUT_SHARE_EXCEEDED,
        422,
    )
    refused = validate_success(
        api.get_experiment(too_large["id"], users.EXPERIMENT_DESIGNER)
    )
    assert refused["status"] == "DRAFT"
    assert refused["version"] == 1

    locked = validate_success(
        api.lock_design(fits["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert _num(locked["power_index"]) == Decimal("3.1944")
    assert _num(locked["computed_power"]) == Decimal("0.9000")
    assert locked["treatment_population"] == 0
    assert locked["control_population"] == 0

    unchanged = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert unchanged["held_out_population"] == 1000000
    assert _num(unchanged["held_out_population_pct"]) == Decimal("10.00")


def test_design_type_decides_which_of_assign_cells_and_start_is_legal(
    api: ApiClient,
) -> None:
    """The same two calls swap legality between the two design types.

    On assigning cells: "Below it, the design must actually be `GEO_HOLDOUT` or
    the answer is `ERR_DESIGN_TYPE_MISMATCH`, and every listed cell must belong to
    the experiment's market or the answer is `ERR_GEO_CELL_NOT_IN_MARKET`." On
    starting: "A `GEO_HOLDOUT` experiment reaches `RUNNING` from `CELLS_ASSIGNED`;
    attempting it directly from `DESIGN_LOCKED` is refused with
    `ERR_CELLS_NOT_ASSIGNED`, because the arms do not exist yet." Whereas: "An
    `AUDIENCE_SPLIT` experiment reaches `RUNNING` straight from `DESIGN_LOCKED`,
    and that step (re)asserts `treatment_population` from
    `planned_treatment_population` and `control_population` from
    `planned_control_population`."

    The same conditional shows from the population side, since at lock time "For
    an `AUDIENCE_SPLIT` design it also copies `planned_treatment_population` into
    `treatment_population` and `planned_control_population` into
    `control_population`, because that design has nothing further to enlist."
    while on assigning cells "The experiment's `treatment_population` becomes the
    summed population of its treatment cells and its `control_population` the
    summed population of its control cells."

    The clock stands one day past both start dates throughout, so a refusal to
    start cannot be a temporal refusal.

    Design: Corner/validations/design_type_conditional_validation_on_assign_cells_and_start
    """
    ctx = fx.market_with_channels(api)
    cells = fx.create_geo_cells(
        api, ctx["market"]["id"], [("GC01", 100000), ("GC02", 100000)]
    )
    body = f.assign_cells_payload([cells[0]["id"]], [cells[1]["id"]])

    audience = fx.locked_experiment(api, ctx)
    geo = fx.locked_experiment(
        api,
        ctx,
        experiment=fx.create_experiment(
            api,
            ctx,
            channel_id=ctx["b_social"]["id"],
            geo=True,
            planned_population=f.EXPERIMENT_ARM_POPULATION,
        ),
    )
    fx.set_clock(api, CLOCK_ONE_DAY_AFTER_START)

    validate_error(
        api.assign_cells(audience["id"], body, users.EXPERIMENT_DESIGNER),
        ApiErrorId.ERR_DESIGN_TYPE_MISMATCH,
        422,
    )
    untouched = validate_success(
        api.get_geo_cell(cells[0]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert untouched["assignment_state"] == "UNASSIGNED"

    validate_error(
        api.start_experiment(geo["id"], users.EXPERIMENT_DESIGNER),
        ApiErrorId.ERR_CELLS_NOT_ASSIGNED,
        422,
    )

    # The identical body that the audience design refused is accepted here.
    assigned = validate_success(
        api.assign_cells(geo["id"], body, users.EXPERIMENT_DESIGNER)
    )
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == 100000
    assert assigned["control_population"] == 100000

    started = validate_success(
        api.start_experiment(audience["id"], users.EXPERIMENT_DESIGNER)
    )
    assert started["status"] == "RUNNING"

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 200000
    assert _num(market["held_out_population_pct"]) == Decimal("2.00")

    planned_side = validate_success(
        api.get_experiment(audience["id"], users.EXPERIMENT_DESIGNER)
    )
    assert planned_side["treatment_population"] == 245000
    realised_side = validate_success(
        api.get_experiment(geo["id"], users.EXPERIMENT_DESIGNER)
    )
    assert realised_side["treatment_population"] == 100000


def test_a_negative_baseline_rolls_the_whole_fit_back(api: ApiClient) -> None:
    """A fit whose channel effects exceed the market's sales writes nothing.

    "If that subtraction would come out negative — the channels between them
    claiming more units than the market actually sold — the fit is rejected with
    `ERR_MODEL_BASELINE_NEGATIVE` and **no** row is written: neither the
    contribution rows nor any change to the run's four status dimensions survives
    the attempt."

    The window below carries four live spend rows and four periods against a lag
    of two, so the referential and constraint gates in front of the baseline both
    pass and the baseline gate is the one that can fire: "And every included
    channel must have at least one non-superseded spend observation inside the
    window, or `ERR_NO_SPEND_OBSERVATIONS`."

    Design: Corner/validations/cascading_validation_baseline_negative_on_fit
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    channel = fx.create_channel(
        api,
        f.media_channel_payload(
            market["id"],
            channel_code="C_TV",
            channel_type="VIDEO",
            response_ceiling_units=20000,
        ),
    )
    window = fx.create_data_window(api, market["id"])
    fx.file_sales_rows(api, window["id"])
    fx.file_spend_chain(
        api,
        window["id"],
        _spend_entries(channel["id"], f.WINDOW_PERIODS, f.F1_SPEND_A_SEARCH),
    )
    _seal(api, window["id"], fx.CLOCK_WINDOW_ELAPSED)

    run = _run_over(api, market["id"], window["id"], [channel["id"]])
    before = validate_success(api.get_model_run(run["id"], users.MODELER))

    validate_error(
        api.fit_model_run(run["id"], users.MODELER),
        ApiErrorId.ERR_MODEL_BASELINE_NEGATIVE,
        422,
    )

    after = validate_success(api.get_model_run(run["id"], users.MODELER))
    assert after["fit_status"] == "PENDING"
    assert after["version"] == before["version"]

    rows, meta = validate_paginated(
        api.list_channel_contributions(users.MODELER, {"model_run_id": run["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []

    still_sealed = validate_success(
        api.get_data_window(window["id"], users.DATA_ENGINEER)
    )
    assert still_sealed["status"] == "SEALED"


def test_the_clock_refuses_a_rewind_and_accepts_its_own_current_value(
    api: ApiClient,
) -> None:
    """A rewind is refused, a restatement of the same instant is not.

    "The clock only moves forward: a request naming an instant earlier than the
    clock's current value is rejected with `ERR_CLOCK_REWIND` (HTTP 422)."

    The refusal is observable through a temporal precondition rather than through
    the clock alone, since "The window must have elapsed — the current logical
    clock must be at or after `window_end_date`, otherwise the request is refused
    with `ERR_DATA_WINDOW_NOT_ELAPSED`." A window ending 2026-08-31 could not seal
    at 2026-08-15, so the seal that follows proves the rewind never took effect.

    Design: Corner/validations/clock_rewind_rejected
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    window = fx.create_data_window(api, market["id"])
    fx.file_sales_rows(api, window["id"])
    fx.set_clock(api, f.SECOND_WINDOW_START)

    validate_error(
        api.set_clock("2026-08-15T00:00:00Z", users.DATA_ENGINEER),
        ApiErrorId.ERR_CLOCK_REWIND,
        422,
    )
    # Naming the current instant again is not earlier than the current instant.
    validate_success(api.set_clock(f.SECOND_WINDOW_START, users.DATA_ENGINEER))

    sealed = validate_success(
        api.seal_data_window(window["id"], users.DATA_ENGINEER)
    )
    assert sealed["status"] == "SEALED"

    final = validate_success(
        api.get_data_window(window["id"], users.DATA_ENGINEER)
    )
    assert final["sales_period_count"] == 4
    assert _num(final["lag_completeness_pct"]) == Decimal("100.00")
