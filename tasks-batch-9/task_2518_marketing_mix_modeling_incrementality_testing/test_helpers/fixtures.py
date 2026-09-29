"""Composite setup helpers, layered from the clock upwards.

The harness kills and relaunches the API against an empty database before every
single test, so nothing here may assume state left behind by another test: each
helper builds its whole precondition chain from scratch through the endpoints the
contract declares.

The tiers are:

    Tier 1  the logical clock
    Tier 2  a market, its channels and its geo cells
    Tier 3  a data window carrying four sales periods and eight spend rows
    Tier 4  that window sealed, then a run fitted, validated and published on it
    Tier 5  the downstream objects a published run unlocks: experiments through
            their whole lifecycle, calibration records, budget scenarios with
            allocations, optimized and approved plans, reconciliation reports

Every tier returns a plain dictionary of the rows it created and threads the
dictionary of the tier below it, so a test may stop at whatever depth its claim
needs. The numbers baked into the canonical chain are the ones the arithmetic
sections of the contract turn into the pinned figures recorded at the bottom of
this module.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from . import test_users as users
from .api_client import ApiClient
from .constants import DEFAULT_CLOCK_UTC
from .types import Json, JsonList

# ---------------------------------------------------------------------------
# Clock instants the chain relies on
# ---------------------------------------------------------------------------

# The instant at which the canonical window has elapsed and may be sealed.
CLOCK_WINDOW_ELAPSED = "2026-08-31T00:00:00Z"
# The instant at which the canonical experiment may be started.
CLOCK_EXPERIMENT_STARTED = "2026-09-07T00:00:00Z"
# The instant at which the canonical experiment has elapsed and may be read out.
CLOCK_EXPERIMENT_ELAPSED = "2026-10-05T00:00:00Z"
# One day before the canonical washout deadline of 2026-10-12.
CLOCK_BEFORE_WASHOUT_ELAPSED = "2026-10-11T00:00:00Z"
# The canonical washout deadline itself: end_date 2026-10-05 plus seven days.
CLOCK_WASHOUT_ELAPSED = "2026-10-12T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — the logical clock
# ---------------------------------------------------------------------------


def set_clock(
    api: ApiClient,
    instant: str = DEFAULT_CLOCK_UTC,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Move the clock forward. Every role except Auditor may do this."""
    response = api.set_clock(instant, headers or users.DATA_ENGINEER)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 2 — market, channels, cells
# ---------------------------------------------------------------------------


def create_market(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_market(f.market_payload(**overrides), users.DATA_ENGINEER), 201
    )


def create_second_market(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_market(f.second_market_payload(**overrides), users.DATA_ENGINEER),
        201,
    )


def create_channel(api: ApiClient, payload: Dict[str, Any]) -> Json:
    return validate_success(
        api.create_media_channel(payload, users.DATA_ENGINEER), 201
    )


def create_geo_cell(
    api: ApiClient, market_id: str, cell_code: str, population: int
) -> Json:
    return validate_success(
        api.create_geo_cell(
            f.geo_cell_payload(market_id, cell_code=cell_code, population=population),
            users.DATA_ENGINEER,
        ),
        201,
    )


def create_geo_cells(
    api: ApiClient, market_id: str, specs: List[Tuple[str, int]]
) -> JsonList:
    """A pool of cells, created in the order given."""
    return [
        create_geo_cell(api, market_id, cell_code, population)
        for cell_code, population in specs
    ]


def market_with_channels(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK_UTC,
    market_overrides: Optional[Dict[str, Any]] = None,
    a_search_overrides: Optional[Dict[str, Any]] = None,
    b_social_overrides: Optional[Dict[str, Any]] = None,
) -> Json:
    """The canonical market with A_SEARCH and B_SOCIAL, created in that order."""
    set_clock(api, clock)
    market = create_market(api, **(market_overrides or {}))
    a_search = create_channel(
        api, f.a_search_payload(market["id"], **(a_search_overrides or {}))
    )
    b_social = create_channel(
        api, f.b_social_payload(market["id"], **(b_social_overrides or {}))
    )
    return {
        "market": market,
        "a_search": a_search,
        "b_social": b_social,
        "channel_ids": [a_search["id"], b_social["id"]],
    }


# ---------------------------------------------------------------------------
# Tier 3 — a data window with its sales and spend history
# ---------------------------------------------------------------------------


def create_data_window(api: ApiClient, market_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_data_window(
            f.data_window_payload(market_id, **overrides), users.DATA_ENGINEER
        ),
        201,
    )


def window_version(api: ApiClient, window_id: str) -> int:
    """Read the window's current version, which the spend rule serializes on."""
    window = validate_success(api.get_data_window(window_id, users.DATA_ENGINEER))
    return window["version"]


def file_sales_rows(
    api: ApiClient,
    window_id: str,
    periods: Optional[List[str]] = None,
    rows: Optional[List[Dict[str, int]]] = None,
) -> JsonList:
    """File one sales observation per period, in period order."""
    periods = periods or f.WINDOW_PERIODS
    rows = rows or f.F1_SALES_ROWS
    created: JsonList = []
    for period, row in zip(periods, rows):
        created.append(
            validate_success(
                api.create_sales_observation(
                    f.sales_observation_payload(
                        window_id,
                        period,
                        row["units_sold"],
                        row["revenue_cents"],
                    ),
                    users.DATA_ENGINEER,
                ),
                201,
            )
        )
    return created


def file_spend_chain(
    api: ApiClient,
    window_id: str,
    entries: List[Tuple[str, str, Dict[str, int]]],
    start_version: Optional[int] = None,
) -> JsonList:
    """File a chain of spend observations, threading the window version.

    Each write must present the window's current version, and the response hands
    back the version the write left behind, so the chain reads the version once
    and then follows `data_window_version_after` from row to row.
    """
    version = (
        start_version if start_version is not None else window_version(api, window_id)
    )
    created: JsonList = []
    for channel_id, period, row in entries:
        observation = validate_success(
            api.create_spend_observation(
                f.spend_observation_payload(
                    window_id,
                    channel_id,
                    period,
                    row["spend_cents"],
                    version,
                    impressions=row.get("impressions"),
                ),
                users.DATA_ENGINEER,
            ),
            201,
        )
        version = observation["data_window_version_after"]
        created.append(observation)
    return created


def f1_spend_entries(
    a_search_id: str,
    b_social_id: str,
    periods: Optional[List[str]] = None,
) -> List[Tuple[str, str, Dict[str, int]]]:
    """The canonical eight spend writes: four for A_SEARCH, then four for B_SOCIAL."""
    periods = periods or f.WINDOW_PERIODS
    entries: List[Tuple[str, str, Dict[str, int]]] = []
    for period, row in zip(periods, f.F1_SPEND_A_SEARCH):
        entries.append((a_search_id, period, row))
    for period, row in zip(periods, f.F1_SPEND_B_SOCIAL):
        entries.append((b_social_id, period, row))
    return entries


def window_with_observations(
    api: ApiClient,
    clock: str = DEFAULT_CLOCK_UTC,
    market_overrides: Optional[Dict[str, Any]] = None,
    a_search_overrides: Optional[Dict[str, Any]] = None,
    b_social_overrides: Optional[Dict[str, Any]] = None,
    window_overrides: Optional[Dict[str, Any]] = None,
) -> Json:
    """The canonical market, its two channels, and a complete OPEN window.

    Four weekly sales periods and eight spend rows are filed, which leaves the
    window at `lag_completeness_pct` 100.00 with four sales periods — the two
    completeness conditions the seal requires.
    """
    ctx = market_with_channels(
        api,
        clock=clock,
        market_overrides=market_overrides,
        a_search_overrides=a_search_overrides,
        b_social_overrides=b_social_overrides,
    )
    window = create_data_window(api, ctx["market"]["id"], **(window_overrides or {}))
    sales = file_sales_rows(api, window["id"])
    spend = file_spend_chain(
        api,
        window["id"],
        f1_spend_entries(ctx["a_search"]["id"], ctx["b_social"]["id"]),
    )
    ctx.update({"window": window, "sales": sales, "spend": spend})
    return ctx


def sealed_window(
    api: ApiClient,
    ctx: Optional[Json] = None,
    clock: str = CLOCK_WINDOW_ELAPSED,
    **kwargs: Any,
) -> Json:
    """A complete window, sealed once the clock has passed its exclusive end."""
    ctx = ctx if ctx is not None else window_with_observations(api, **kwargs)
    set_clock(api, clock)
    ctx["window"] = validate_success(
        api.seal_data_window(ctx["window"]["id"], users.DATA_ENGINEER)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — model runs: declared, fitted, validated, published
# ---------------------------------------------------------------------------


def create_run(
    api: ApiClient,
    ctx: Json,
    included_channel_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Json:
    """Declare a run over a window. Creation performs no fitting."""
    return validate_success(
        api.create_model_run(
            f.model_run_payload(
                ctx["market"]["id"],
                ctx["window"]["id"],
                included_channel_ids or ctx["channel_ids"],
                **overrides,
            ),
            users.MODELER,
        ),
        201,
    )


def contributions_of(api: ApiClient, run_id: str, **params: Any) -> JsonList:
    """The contribution rows the fit wrote, as the list endpoint returns them."""
    query: Dict[str, Any] = {"model_run_id": run_id}
    query.update(params)
    response = api.list_channel_contributions(users.MODELER, query)
    return validate_success(response)


def fitted_run(
    api: ApiClient,
    ctx: Optional[Json] = None,
    carryover_attribution_mode: str = "EFFECT_PERIOD",
    run_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Json:
    """A run fitted against the sealed canonical window.

    The fit writes one contribution row per included channel in ascending
    channel_code order and leaves the run FITTED and UNVALIDATED.
    """
    ctx = ctx if ctx is not None else sealed_window(api, **kwargs)
    overrides = dict(run_overrides or {})
    overrides.setdefault("carryover_attribution_mode", carryover_attribution_mode)
    run = create_run(api, ctx, **overrides)
    run = validate_success(api.fit_model_run(run["id"], users.MODELER))
    ctx["run"] = run
    ctx["contributions"] = contributions_of(api, run["id"])
    return ctx


def validated_run(
    api: ApiClient, ctx: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A fitted run that has been backtested against its holdout period."""
    ctx = ctx if ctx is not None else fitted_run(api, **kwargs)
    ctx["run"] = validate_success(
        api.validate_model_run(ctx["run"]["id"], users.MODELER)
    )
    return ctx


def published_run(
    api: ApiClient,
    ctx: Optional[Json] = None,
    override_stability: Optional[bool] = None,
    **kwargs: Any,
) -> Json:
    """The market's published run: fitted, HOLDOUT_PASSED and published.

    A first publication skips the stability gate, stores `refresh_generation` 1
    and moves the market out of RESTRICTED.
    """
    ctx = ctx if ctx is not None else validated_run(api, **kwargs)
    ctx["run"] = validate_success(
        api.publish_model_run(
            ctx["run"]["id"],
            users.ANALYTICS_LEAD,
            f.publish_payload(override_stability),
        )
    )
    ctx["contributions"] = contributions_of(api, ctx["run"]["id"])
    ctx["market"] = validate_success(
        api.get_market(ctx["market"]["id"], users.ANALYTICS_LEAD)
    )
    return ctx


def refresh_market(api: ApiClient, ctx: Json) -> Json:
    """Re-read the market so its posture and aggregates are current."""
    ctx["market"] = validate_success(
        api.get_market(ctx["market"]["id"], users.ANALYTICS_LEAD)
    )
    return ctx["market"]


def refresh_run(api: ApiClient, ctx: Json) -> Json:
    """Re-read the run so all four state dimensions are current."""
    ctx["run"] = validate_success(api.get_model_run(ctx["run"]["id"], users.MODELER))
    return ctx["run"]


def refresh_window(api: ApiClient, ctx: Json) -> Json:
    ctx["window"] = validate_success(
        api.get_data_window(ctx["window"]["id"], users.DATA_ENGINEER)
    )
    return ctx["window"]


# ---------------------------------------------------------------------------
# Tier 5a — experiments through their lifecycle
# ---------------------------------------------------------------------------


def create_experiment(
    api: ApiClient,
    ctx: Json,
    channel_id: Optional[str] = None,
    geo: bool = False,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    """Draft an experiment on one channel of the market."""
    builder = f.geo_experiment_payload if geo else f.experiment_payload
    return validate_success(
        api.create_experiment(
            builder(
                ctx["market"]["id"],
                channel_id or ctx["a_search"]["id"],
                **overrides,
            ),
            headers or users.EXPERIMENT_DESIGNER,
        ),
        201,
    )


def locked_experiment(
    api: ApiClient, ctx: Json, experiment: Optional[Json] = None, **overrides: Any
) -> Json:
    """A drafted experiment carried through the lock-design gates."""
    experiment = experiment or create_experiment(api, ctx, **overrides)
    return validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    )


def running_experiment(
    api: ApiClient,
    ctx: Json,
    experiment: Optional[Json] = None,
    clock: str = CLOCK_EXPERIMENT_STARTED,
    treatment_cell_ids: Optional[List[str]] = None,
    control_cell_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Json:
    """An experiment in market: locked, cells assigned if it is a geo design."""
    experiment = locked_experiment(api, ctx, experiment=experiment, **overrides)
    if experiment["design_type"] == "GEO_HOLDOUT":
        assert treatment_cell_ids and control_cell_ids, (
            "a geo-holdout design needs cells before it can start"
        )
        experiment = validate_success(
            api.assign_cells(
                experiment["id"],
                f.assign_cells_payload(treatment_cell_ids, control_cell_ids),
                users.EXPERIMENT_DESIGNER,
            )
        )
    set_clock(api, clock)
    return validate_success(
        api.start_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )


def read_out_experiment(
    api: ApiClient,
    ctx: Json,
    experiment: Optional[Json] = None,
    clock: str = CLOCK_EXPERIMENT_ELAPSED,
    readout_overrides: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Json:
    """A running experiment read out with the canonical conversion counts."""
    experiment = experiment or running_experiment(api, ctx, **overrides)
    set_clock(api, clock)
    return validate_success(
        api.read_out_experiment(
            experiment["id"],
            f.read_out_payload(**(readout_overrides or {})),
            users.EXPERIMENT_DESIGNER,
        )
    )


def accepted_experiment(
    api: ApiClient, ctx: Json, experiment: Optional[Json] = None, **overrides: Any
) -> Json:
    """A readout accepted by a lead who is not the designer."""
    experiment = experiment or read_out_experiment(api, ctx, **overrides)
    return validate_success(
        api.accept_experiment(experiment["id"], users.ANALYTICS_LEAD)
    )


def rejected_experiment(
    api: ApiClient,
    ctx: Json,
    experiment: Optional[Json] = None,
    reason: str = "Geo contamination in two DMAs.",
    **overrides: Any,
) -> Json:
    """A readout rejected by a lead who is not the designer; fires no cascade."""
    experiment = experiment or read_out_experiment(api, ctx, **overrides)
    return validate_success(
        api.reject_experiment(
            experiment["id"], f.reject_payload(reason), users.ANALYTICS_LEAD
        )
    )


def experiment_on_published_market(
    api: ApiClient,
    ctx: Optional[Json] = None,
    channel_id: Optional[str] = None,
    **kwargs: Any,
) -> Json:
    """A published run plus one experiment read out on A_SEARCH.

    This is the shape every calibration rule needs: the accept gate wants a
    published run, and a calibration record wants a readout on a channel the run
    included.
    """
    ctx = ctx if ctx is not None else published_run(api, **kwargs)
    ctx["experiment"] = read_out_experiment(
        api, ctx, channel_id=channel_id or ctx["a_search"]["id"]
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5b — calibration records and recalibration
# ---------------------------------------------------------------------------


def run_version(api: ApiClient, run_id: str) -> int:
    """Read the run's current version, which the calibration rule serializes on."""
    run = validate_success(api.get_model_run(run_id, users.MODELER))
    return run["version"]


def file_calibration_record(
    api: ApiClient,
    ctx: Json,
    channel_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    expected_model_run_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Bind one readout to one channel of the run, deriving the multiplier."""
    run_id = ctx["run"]["id"]
    version = (
        expected_model_run_version
        if expected_model_run_version is not None
        else run_version(api, run_id)
    )
    return validate_success(
        api.create_calibration_record(
            f.calibration_record_payload(
                run_id,
                channel_id or ctx["a_search"]["id"],
                experiment_id or ctx["experiment"]["id"],
                version,
            ),
            headers or users.MODELER,
        ),
        201,
    )


def pending_calibration_run(
    api: ApiClient, ctx: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A published run with one live calibration record awaiting application."""
    ctx = ctx if ctx is not None else experiment_on_published_market(api, **kwargs)
    ctx["calibration_record"] = file_calibration_record(api, ctx)
    refresh_run(api, ctx)
    return ctx


def calibrated_run(
    api: ApiClient, ctx: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A run whose live calibration records have been applied to its rows."""
    ctx = ctx if ctx is not None else pending_calibration_run(api, **kwargs)
    ctx["run"] = validate_success(
        api.recalibrate_model_run(ctx["run"]["id"], users.MODELER)
    )
    ctx["contributions"] = contributions_of(api, ctx["run"]["id"])
    refresh_market(api, ctx)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5c — budget scenarios and allocations
# ---------------------------------------------------------------------------


def create_scenario(
    api: ApiClient,
    ctx: Json,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    return validate_success(
        api.create_budget_scenario(
            f.budget_scenario_payload(
                ctx["market"]["id"], ctx["run"]["id"], **overrides
            ),
            headers or users.BRAND_PLANNER,
        ),
        201,
    )


def add_allocation(
    api: ApiClient,
    scenario_id: str,
    channel_id: str,
    baseline_spend_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    return validate_success(
        api.create_budget_allocation(
            f.budget_allocation_payload(
                scenario_id, channel_id, baseline_spend_cents
            ),
            headers or users.BRAND_PLANNER,
        ),
        201,
    )


def allocations_of(api: ApiClient, scenario_id: str, **params: Any) -> JsonList:
    query: Dict[str, Any] = {"budget_scenario_id": scenario_id}
    query.update(params)
    return validate_success(api.list_budget_allocations(users.BRAND_PLANNER, query))


def scenario_with_allocations(
    api: ApiClient,
    ctx: Optional[Json] = None,
    scenario_overrides: Optional[Dict[str, Any]] = None,
    baselines: Optional[List[Tuple[str, int]]] = None,
    **kwargs: Any,
) -> Json:
    """A DRAFT scenario whose baselines add up to the whole budget.

    The optimizer refuses to run unless the baselines sum exactly to
    `total_budget_cents`, so the canonical pair is 1500000 for A_SEARCH against
    2500000 for B_SOCIAL on a 4000000-cent budget.
    """
    ctx = ctx if ctx is not None else published_run(api, **kwargs)
    scenario = create_scenario(api, ctx, **(scenario_overrides or {}))
    pairs = baselines or [
        (ctx["a_search"]["id"], f.BASELINE_A_SEARCH_CENTS),
        (ctx["b_social"]["id"], f.BASELINE_B_SOCIAL_CENTS),
    ]
    allocations = [
        add_allocation(api, scenario["id"], channel_id, baseline)
        for channel_id, baseline in pairs
    ]
    ctx["scenario"] = scenario
    ctx["allocations"] = allocations
    return ctx


def optimized_scenario(
    api: ApiClient, ctx: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A scenario carried through the two-pass waterfall."""
    ctx = ctx if ctx is not None else scenario_with_allocations(api, **kwargs)
    ctx["scenario"] = validate_success(
        api.optimize_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER)
    )
    ctx["allocations"] = allocations_of(api, ctx["scenario"]["id"])
    return ctx


def approved_scenario(
    api: ApiClient, ctx: Optional[Json] = None, **kwargs: Any
) -> Json:
    """An optimized plan approved by a lead who is not its creator."""
    ctx = ctx if ctx is not None else optimized_scenario(api, **kwargs)
    ctx["scenario"] = validate_success(
        api.approve_budget_scenario(ctx["scenario"]["id"], users.ANALYTICS_LEAD)
    )
    return ctx


def refresh_scenario(api: ApiClient, ctx: Json) -> Json:
    ctx["scenario"] = validate_success(
        api.get_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER)
    )
    return ctx["scenario"]


# ---------------------------------------------------------------------------
# Tier 5d — reconciliation reports
# ---------------------------------------------------------------------------


def file_reconciliation_report(
    api: ApiClient,
    ctx: Json,
    a_search_platform_cents: int = f.PLATFORM_A_SEARCH_MATERIAL_CENTS,
    b_social_platform_cents: int = f.PLATFORM_B_SOCIAL_MATERIAL_CENTS,
    reporting_period_start: str = f.WINDOW_START,
    reporting_period_end: str = f.WINDOW_END,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """One platform line per current contribution row, as the contract demands."""
    lines = [
        f.platform_line(ctx["a_search"]["id"], a_search_platform_cents),
        f.platform_line(ctx["b_social"]["id"], b_social_platform_cents),
    ]
    return validate_success(
        api.create_reconciliation_report(
            f.reconciliation_report_payload(
                ctx["run"]["id"],
                lines,
                reporting_period_start=reporting_period_start,
                reporting_period_end=reporting_period_end,
            ),
            headers or users.ANALYTICS_LEAD,
        ),
        201,
    )


def reports_of(api: ApiClient, run_id: str) -> JsonList:
    return validate_success(
        api.list_reconciliation_reports(users.ANALYTICS_LEAD, {"model_run_id": run_id})
    )


# ---------------------------------------------------------------------------
# The figures the canonical chain produces
# ---------------------------------------------------------------------------
#
# These are recorded here so that a test states the number once, in its own
# assertion, and the fixture and the expectation can never drift apart. Every
# figure below follows from the chain above under the arithmetic the contract
# specifies; none of them is re-derived at run time.

# Window aggregates the fit reads.
F1_MODELED_SALES_UNITS = 23000
F1_UNIT_PRICE_CENTS = 5026
F1_OBSERVATION_PERIOD_COUNT = 4
F1_WINDOW_REVENUE_CENTS = 115_600_000

# The window's own version walks 1 on create, 5 after four sales rows, 13 after
# eight spend rows and 14 after the seal.
F1_WINDOW_VERSION_AFTER_CREATE = 1
F1_WINDOW_VERSION_AFTER_SALES = 5
F1_WINDOW_VERSION_AFTER_SPEND = 13
F1_WINDOW_VERSION_AFTER_SEAL = 14

# Raw spend is variant-invariant: the same cents whichever carryover mode is used.
F1_ATTRIBUTED_SPEND_A_SEARCH = 1_800_000
F1_ATTRIBUTED_SPEND_B_SOCIAL = 900_000

# EFFECT_PERIOD: carryover is credited to the period it lands in, truncated at
# the head of the series.
F1_EFFECT_SERIES_A_SEARCH = [400000, 800000, 700000, 800000]
F1_EFFECT_SERIES_B_SOCIAL = [200000, 250000, 450000, 200000]
F1_EFFECT_MEAN_A_SEARCH = 675000
F1_EFFECT_MEAN_B_SOCIAL = 275000
F1_EFFECT_CONTRIBUTION_A_SEARCH = 3653.3333
F1_EFFECT_CONTRIBUTION_B_SOCIAL = 2014.2857
F1_EFFECT_BASELINE_UNITS = 17332.3810
F1_EFFECT_REVENUE_A_SEARCH = 18_361_653
F1_EFFECT_REVENUE_B_SOCIAL = 10_123_800
F1_EFFECT_AVERAGE_ROI_A_SEARCH = 10.2009
F1_EFFECT_AVERAGE_ROI_B_SOCIAL = 11.2487
F1_EFFECT_MARGINAL_ROI_A_SEARCH = 1.575497
F1_EFFECT_MARGINAL_ROI_B_SOCIAL = 3.339073
F1_EFFECT_CI_LOW_A_SEARCH = 2922.6666
F1_EFFECT_CI_HIGH_A_SEARCH = 4384.0000

# SPEND_PERIOD: the whole geometric gain is credited to the spending period.
F1_SPEND_SERIES_A_SEARCH = [700000, 1050000, 525000, 875000]
F1_SPEND_SERIES_B_SOCIAL = [250000, 250000, 500000, 125000]
F1_SPEND_MEAN_A_SEARCH = 787500
F1_SPEND_MEAN_B_SOCIAL = 281250
F1_SPEND_CONTRIBUTION_A_SEARCH = 3787.0430
F1_SPEND_CONTRIBUTION_B_SOCIAL = 1979.0210
F1_SPEND_BASELINE_UNITS = 17233.9360
F1_SPEND_REVENUE_A_SEARCH = 19_033_678
F1_SPEND_REVENUE_B_SOCIAL = 9_946_560
F1_SPEND_AVERAGE_ROI_A_SEARCH = 10.5743
F1_SPEND_AVERAGE_ROI_B_SOCIAL = 11.0517
F1_SPEND_MARGINAL_ROI_A_SEARCH = 1.236971
F1_SPEND_MARGINAL_ROI_B_SOCIAL = 3.242989
F1_SPEND_CI_LOW_A_SEARCH = 3029.6344
F1_SPEND_CI_HIGH_A_SEARCH = 4544.4516

# The interval half width depends only on the run-level period count, so both
# channels share it under either mode.
F1_CI_HALF_WIDTH_PCT = 20.00

# The backtest over the single holdout period.
F1_EFFECT_HOLDOUT_PREDICTION = 5750.2382
F1_EFFECT_HOLDOUT_MAPE_PCT = 11.53
F1_SPEND_HOLDOUT_PREDICTION = 5648.8646
F1_SPEND_HOLDOUT_MAPE_PCT = 13.09
F1_HOLDOUT_ACTUAL_UNITS = 6500
F1_BASELINE_PER_PERIOD_UNITS = 4333.0953
F1_HOLDOUT_TERM_A_SEARCH = 960.0000
F1_HOLDOUT_TERM_B_SOCIAL = 457.1429

# Experiment power: the canonical arms land exactly on the 2.5000 table boundary.
F1_POWER_INDEX_BOUNDARY = 2.5000
F1_COMPUTED_POWER_BOUNDARY = 0.8000
F1_POWER_INDEX_BELOW = 2.0000
F1_COMPUTED_POWER_BELOW = 0.7500
F1_POWER_INDEX_ABOVE = 3.0000
F1_COMPUTED_POWER_ABOVE = 0.9000

# Readout figures off the canonical conversion counts.
F1_DID_MEASURED_LIFT_PCT = 10.00
F1_DID_CI_LOW_PCT = 6.03
F1_DID_CI_HIGH_PCT = 13.97
F1_SYNTHETIC_WEIGHT = 0.950000
F1_SYNTHETIC_MEASURED_LIFT_PCT = 10.53
F1_SYNTHETIC_CI_LOW_PCT = 6.56
F1_SYNTHETIC_CI_HIGH_PCT = 14.50
F1_LIFT_CI_HALF_WIDTH_PCT = 3.97

# Calibration off the EFFECT_PERIOD fit and the difference-in-differences lift.
F1_MODEL_IMPLIED_LIFT_PCT = 18.8835
F1_CALIBRATION_MULTIPLIER = 0.5296
F1_CALIBRATED_UNITS_A_SEARCH = 1934.8053
F1_CALIBRATED_REVENUE_A_SEARCH = 9_724_331
F1_CALIBRATED_BASELINE_UNITS = 19050.9090

# The two-pass budget waterfall on the canonical 4000000-cent plan.
F1_PLANNING_PERIOD_COUNT = 4
F1_PASS1_A_SEARCH_CENTS = 2_400_000
F1_PASS1_B_SOCIAL_CENTS = 1_600_000
F1_PASS1_CHURN_CENTS = 1_800_000
F1_REALLOCATION_FEE_CENTS = 9_000
F1_ALLOCATED_A_SEARCH_CENTS = 2_300_000
F1_ALLOCATED_B_SOCIAL_CENTS = 1_600_000
F1_ALLOCATED_TOTAL_CENTS = 3_900_000
F1_SHIFTED_A_SEARCH_CENTS = 800_000
F1_SHIFTED_B_SOCIAL_CENTS = 900_000
F1_SHIFTED_TOTAL_CENTS = 1_700_000
F1_UNALLOCATED_CENTS = 91_000
F1_PROJECTED_UNITS_A_SEARCH = 3561.2903
F1_PROJECTED_UNITS_B_SOCIAL = 2327.2727
F1_PROJECTED_UNITS_TOTAL = 5888.5630
F1_PROJECTED_REVENUE_CENTS = 29_595_918
# The fee a second pass would have produced had it been recomputed: it must
# never appear, because the fee is pinned at its pass-one value.
F1_FORBIDDEN_RECOMPUTED_FEE_CENTS = 8_500

# Reconciliation against the EFFECT_PERIOD contributions, RAW basis.
F1_RAW_MODEL_ATTRIBUTED_CENTS = 28_485_453
F1_RAW_PLATFORM_REPORTED_CENTS = 32_756_000
F1_RAW_TOTAL_VARIANCE_CENTS = 4_270_547
F1_RAW_VARIANCE_A_SEARCH_CENTS = 638_347
F1_RAW_VARIANCE_A_SEARCH_PCT = 3.48
F1_RAW_VARIANCE_B_SOCIAL_CENTS = 3_632_200
F1_RAW_VARIANCE_B_SOCIAL_PCT = 35.88
F1_RAW_WEIGHTED_VARIANCE_PCT = 15.00
# What the rejected weight-then-round order would have produced.
F1_FORBIDDEN_WEIGHTED_VARIANCE_PCT = 14.99

# A second, immaterial report over the September period.
F1_IMMATERIAL_PERIOD_START = "2026-09-01T00:00:00Z"
F1_IMMATERIAL_PERIOD_END = "2026-09-29T00:00:00Z"
F1_IMMATERIAL_VARIANCE_A_SEARCH_CENTS = 3_638_347
F1_IMMATERIAL_VARIANCE_A_SEARCH_PCT = 19.81
F1_IMMATERIAL_VARIANCE_B_SOCIAL_CENTS = -1_123_800
F1_IMMATERIAL_VARIANCE_B_SOCIAL_PCT = -11.10
F1_IMMATERIAL_TOTAL_VARIANCE_CENTS = 2_514_547
F1_IMMATERIAL_WEIGHTED_VARIANCE_PCT = 8.82
F1_FORBIDDEN_IMMATERIAL_WEIGHTED_PCT = 8.83

# Reconciliation on the CALIBRATED basis, after the multiplier is applied.
F1_CALIBRATED_MODEL_ATTRIBUTED_CENTS = 19_848_131
F1_CALIBRATED_VARIANCE_A_SEARCH_CENTS = 9_275_669
F1_CALIBRATED_VARIANCE_A_SEARCH_PCT = 95.39
F1_CALIBRATED_TOTAL_VARIANCE_CENTS = 12_907_869
F1_CALIBRATED_WEIGHTED_VARIANCE_PCT = 65.04

# The holdout-share ceiling in exact integers: two million-person cells land
# exactly on twenty percent of a ten-million market, and one extra person does not.
F1_CEILING_CELL_POPULATION = 1_000_000
F1_CEILING_CELL_POPULATION_OVER = 1_000_100
F1_HOLDOUT_CEILING_POPULATION = 2_000_000
