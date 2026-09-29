"""Request-body builders.

Each builder returns a complete, admissible body for one endpoint and accepts
keyword overrides, so a test that cares about a single field says so and nothing
else. The defaults describe one canonical market — a two-channel US market with
a four-period weekly training window — because almost every rule in the contract
needs a fitted model before it can be reached at all.

Only fields the endpoint actually declares appear here; nothing computed by the
server is ever sent.
"""

from typing import Any, Dict, List, Optional

from .types import Json, Payload, PlatformLine

# ---------------------------------------------------------------------------
# The canonical market
# ---------------------------------------------------------------------------

MARKET_CODE = "US_CORE"
MARKET_NAME = "US Core Brand Market"
MARKET_TOTAL_POPULATION = 10_000_000
MARKET_BUDGET_CEILING_CENTS = 5_000_000_000

SECOND_MARKET_CODE = "EU_CORE"
SECOND_MARKET_NAME = "EU Core Brand Market"


def market_payload(**overrides: Any) -> Payload:
    """A market with a ten-million population and a fifty-million-dollar ceiling."""
    payload: Payload = {
        "market_code": MARKET_CODE,
        "name": MARKET_NAME,
        "total_population": MARKET_TOTAL_POPULATION,
        "annual_budget_ceiling_cents": MARKET_BUDGET_CEILING_CENTS,
        "currency_code": "USD",
    }
    payload.update(overrides)
    return payload


def second_market_payload(**overrides: Any) -> Payload:
    """A second, unrelated market, for cross-market referential probes."""
    payload = market_payload(
        market_code=SECOND_MARKET_CODE,
        name=SECOND_MARKET_NAME,
        currency_code="EUR",
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Media channels
# ---------------------------------------------------------------------------


def media_channel_payload(market_id: str, **overrides: Any) -> Payload:
    """A generic channel; callers normally use one of the two named builders."""
    payload: Payload = {
        "market_id": market_id,
        "channel_code": "A_SEARCH",
        "channel_type": "SEARCH",
        "adstock_decay_rate": 0.5,
        "adstock_max_lag_periods": 2,
        "saturation_half_point_cents": 200000,
        "response_ceiling_units": 1200,
        "min_spend_cents": 200000,
        "max_spend_cents": 3000000,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def a_search_payload(market_id: str, **overrides: Any) -> Payload:
    """A_SEARCH: decay 0.50 over two lag periods, half point 200000, ceiling 1200."""
    return media_channel_payload(market_id, **overrides)


def b_social_payload(market_id: str, **overrides: Any) -> Payload:
    """B_SOCIAL: decay 0.25 over one lag period, half point 150000, ceiling 800."""
    payload = media_channel_payload(
        market_id,
        channel_code="B_SOCIAL",
        channel_type="SOCIAL",
        adstock_decay_rate=0.25,
        adstock_max_lag_periods=1,
        saturation_half_point_cents=150000,
        response_ceiling_units=800,
        min_spend_cents=100000,
        max_spend_cents=3000000,
    )
    payload.update(overrides)
    return payload


def c_video_payload(market_id: str, **overrides: Any) -> Payload:
    """C_VIDEO: a third channel, used where a channel must sort last."""
    payload = media_channel_payload(
        market_id,
        channel_code="C_VIDEO",
        channel_type="VIDEO",
        adstock_decay_rate=0.3,
        adstock_max_lag_periods=1,
        saturation_half_point_cents=300000,
        response_ceiling_units=900,
        min_spend_cents=100000,
        max_spend_cents=2000000,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Geo cells
# ---------------------------------------------------------------------------


def geo_cell_payload(
    market_id: str, cell_code: str = "GC01", population: int = 1_000_000, **overrides: Any
) -> Payload:
    payload: Payload = {
        "market_id": market_id,
        "cell_code": cell_code,
        "population": population,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Data windows and their periods
# ---------------------------------------------------------------------------

# The canonical window is the four-week half-open range [2026-08-03, 2026-08-31).
WINDOW_START = "2026-08-03T00:00:00Z"
WINDOW_END = "2026-08-31T00:00:00Z"
WINDOW_PERIODS: List[str] = [
    "2026-08-03T00:00:00Z",
    "2026-08-10T00:00:00Z",
    "2026-08-17T00:00:00Z",
    "2026-08-24T00:00:00Z",
]

# A second, non-overlapping window, for posture swings and overlap probes.
SECOND_WINDOW_START = "2026-09-01T00:00:00Z"
SECOND_WINDOW_END = "2026-09-29T00:00:00Z"
SECOND_WINDOW_PERIODS: List[str] = [
    "2026-09-01T00:00:00Z",
    "2026-09-08T00:00:00Z",
    "2026-09-15T00:00:00Z",
    "2026-09-22T00:00:00Z",
]


def data_window_payload(market_id: str, **overrides: Any) -> Payload:
    payload: Payload = {
        "market_id": market_id,
        "window_start_date": WINDOW_START,
        "window_end_date": WINDOW_END,
        "granularity": "WEEKLY",
    }
    payload.update(overrides)
    return payload


def second_data_window_payload(market_id: str, **overrides: Any) -> Payload:
    payload = data_window_payload(
        market_id,
        window_start_date=SECOND_WINDOW_START,
        window_end_date=SECOND_WINDOW_END,
    )
    payload.update(overrides)
    return payload


def reopen_payload(reason: str = "Media agency restated August search spend.") -> Payload:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

# The four sales periods of the canonical window. Units and revenue are chosen so
# that the window totals are 23000 units against 115600000 cents, which is what
# the fit turns into a unit_price_cents of 5026.
F1_SALES_ROWS: List[Dict[str, int]] = [
    {"units_sold": 5000, "revenue_cents": 25000000},
    {"units_sold": 6000, "revenue_cents": 30600000},
    {"units_sold": 5500, "revenue_cents": 27500000},
    {"units_sold": 6500, "revenue_cents": 32500000},
]

# Raw weekly spend for the two canonical channels, period by period.
F1_SPEND_A_SEARCH: List[Dict[str, int]] = [
    {"spend_cents": 400000, "impressions": 4000},
    {"spend_cents": 600000, "impressions": 6000},
    {"spend_cents": 300000, "impressions": 3000},
    {"spend_cents": 500000, "impressions": 5000},
]
F1_SPEND_B_SOCIAL: List[Dict[str, int]] = [
    {"spend_cents": 200000, "impressions": 2000},
    {"spend_cents": 200000, "impressions": 2000},
    {"spend_cents": 400000, "impressions": 4000},
    {"spend_cents": 100000, "impressions": 1000},
]


def sales_observation_payload(
    data_window_id: str,
    period_start_date: str,
    units_sold: int,
    revenue_cents: int,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "data_window_id": data_window_id,
        "period_start_date": period_start_date,
        "units_sold": units_sold,
        "revenue_cents": revenue_cents,
        "distribution_pct": 82.0,
        "macro_index": 100.0,
    }
    payload.update(overrides)
    return payload


def spend_observation_payload(
    data_window_id: str,
    channel_id: str,
    period_start_date: str,
    spend_cents: int,
    expected_data_window_version: int,
    impressions: Optional[int] = None,
    **overrides: Any,
) -> Payload:
    """A spend observation, always carrying the window version it serializes on."""
    payload: Payload = {
        "data_window_id": data_window_id,
        "channel_id": channel_id,
        "period_start_date": period_start_date,
        "spend_cents": spend_cents,
        "impressions": impressions if impressions is not None else spend_cents // 100,
        "price_index": 100.0,
        "distribution_index": 100.0,
        "expected_data_window_version": expected_data_window_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Model runs
# ---------------------------------------------------------------------------


def model_run_payload(
    market_id: str,
    data_window_id: str,
    included_channel_ids: List[str],
    **overrides: Any,
) -> Payload:
    """A run declaration. Creation performs no fitting."""
    payload: Payload = {
        "market_id": market_id,
        "data_window_id": data_window_id,
        "included_channel_ids": list(included_channel_ids),
        "control_variables": ["PRICE_INDEX", "MACRO_INDEX"],
        "seasonality_mode": "WEEK_OF_YEAR",
        "carryover_attribution_mode": "EFFECT_PERIOD",
        "holdout_periods": 1,
    }
    payload.update(overrides)
    return payload


def publish_payload(override_stability: Optional[bool] = None) -> Payload:
    """The publish body; the stability override is the only field it carries."""
    if override_stability is None:
        return {}
    return {"override_stability": override_stability}


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

# The canonical audience-split design: two arms of 245000 at a 2 percent
# baseline conversion rate and a 5 percent minimum detectable effect, which is
# exactly the power_index 2.5000 boundary case.
EXPERIMENT_START = "2026-09-07T00:00:00Z"
EXPERIMENT_END = "2026-10-05T00:00:00Z"
EXPERIMENT_ARM_POPULATION = 245000


def experiment_payload(
    market_id: str, channel_id: str, **overrides: Any
) -> Payload:
    payload: Payload = {
        "market_id": market_id,
        "channel_id": channel_id,
        "design_type": "AUDIENCE_SPLIT",
        "readout_method": "DIFF_IN_DIFF",
        "start_date": EXPERIMENT_START,
        "end_date": EXPERIMENT_END,
        "washout_days": 7,
        "minimum_detectable_effect_pct": 5.0,
        "baseline_conversion_rate": 0.02,
        "planned_treatment_population": EXPERIMENT_ARM_POPULATION,
        "planned_control_population": EXPERIMENT_ARM_POPULATION,
    }
    payload.update(overrides)
    return payload


def geo_experiment_payload(
    market_id: str,
    channel_id: str,
    planned_population: int = 1_000_000,
    **overrides: Any,
) -> Payload:
    """A geo-holdout design, whose arms are realised by assigning cells."""
    payload = experiment_payload(
        market_id,
        channel_id,
        design_type="GEO_HOLDOUT",
        planned_treatment_population=planned_population,
        planned_control_population=planned_population,
    )
    payload.update(overrides)
    return payload


def assign_cells_payload(
    treatment_cell_ids: List[str], control_cell_ids: List[str]
) -> Payload:
    return {
        "treatment_cell_ids": list(treatment_cell_ids),
        "control_cell_ids": list(control_cell_ids),
    }


# The canonical readout: a 10 percent lift under difference-in-differences and a
# 10.53 percent lift under the synthetic control estimator, off identical counts.
READOUT_TREATMENT_CONVERSIONS = 5145
READOUT_CONTROL_CONVERSIONS = 4900
READOUT_PRE_TREATMENT_CONVERSIONS = 4655
READOUT_PRE_CONTROL_CONVERSIONS = 4900


def read_out_payload(**overrides: Any) -> Payload:
    payload: Payload = {
        "treatment_conversions": READOUT_TREATMENT_CONVERSIONS,
        "control_conversions": READOUT_CONTROL_CONVERSIONS,
        "pre_treatment_conversions": READOUT_PRE_TREATMENT_CONVERSIONS,
        "pre_control_conversions": READOUT_PRE_CONTROL_CONVERSIONS,
    }
    payload.update(overrides)
    return payload


def reject_payload(
    rejection_reason: str = "Geo contamination in two DMAs.",
) -> Payload:
    return {"rejection_reason": rejection_reason}


# ---------------------------------------------------------------------------
# Calibration records
# ---------------------------------------------------------------------------


def calibration_record_payload(
    model_run_id: str,
    channel_id: str,
    experiment_id: str,
    expected_model_run_version: int,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "model_run_id": model_run_id,
        "channel_id": channel_id,
        "experiment_id": experiment_id,
        "expected_model_run_version": expected_model_run_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Budget scenarios and allocations
# ---------------------------------------------------------------------------

# The canonical plan: a four-week November horizon against a 4000000-cent budget
# with a half-percent reallocation fee.
PLANNING_START = "2026-11-02T00:00:00Z"
PLANNING_END = "2026-11-30T00:00:00Z"
SCENARIO_TOTAL_BUDGET_CENTS = 4_000_000
SCENARIO_FEE_PCT = 0.5

# Baselines that add up to the whole budget, as the optimizer requires.
BASELINE_A_SEARCH_CENTS = 1_500_000
BASELINE_B_SOCIAL_CENTS = 2_500_000


def budget_scenario_payload(
    market_id: str, model_run_id: str, **overrides: Any
) -> Payload:
    payload: Payload = {
        "market_id": market_id,
        "model_run_id": model_run_id,
        "total_budget_cents": SCENARIO_TOTAL_BUDGET_CENTS,
        "planning_start_date": PLANNING_START,
        "planning_end_date": PLANNING_END,
        "reallocation_fee_pct": SCENARIO_FEE_PCT,
    }
    payload.update(overrides)
    return payload


def budget_allocation_payload(
    budget_scenario_id: str,
    channel_id: str,
    baseline_spend_cents: int,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "budget_scenario_id": budget_scenario_id,
        "channel_id": channel_id,
        "baseline_spend_cents": baseline_spend_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reconciliation reports
# ---------------------------------------------------------------------------

# Platform figures that put the weighted gap exactly on 15.00 under the mandated
# round-then-weight order, and on 14.99 under the rejected order.
PLATFORM_A_SEARCH_MATERIAL_CENTS = 19_000_000
PLATFORM_B_SOCIAL_MATERIAL_CENTS = 13_756_000

# Platform figures that leave the gap immaterial at 8.82 percent.
PLATFORM_A_SEARCH_IMMATERIAL_CENTS = 22_000_000
PLATFORM_B_SOCIAL_IMMATERIAL_CENTS = 9_000_000


def platform_line(channel_id: str, platform_revenue_cents: int) -> PlatformLine:
    return {
        "channel_id": channel_id,
        "platform_revenue_cents": platform_revenue_cents,
    }


def reconciliation_report_payload(
    model_run_id: str,
    platform_lines: List[PlatformLine],
    reporting_period_start: str = WINDOW_START,
    reporting_period_end: str = WINDOW_END,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "model_run_id": model_run_id,
        "reporting_period_start": reporting_period_start,
        "reporting_period_end": reporting_period_end,
        "platform_lines": list(platform_lines),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def without(payload: Payload, *fields: str) -> Payload:
    """A copy of a body with the named fields removed (missing-field probes)."""
    return {k: v for k, v in payload.items() if k not in fields}


def with_extra(payload: Payload, **extras: Any) -> Payload:
    """A copy of a body carrying additional, undeclared fields."""
    merged = dict(payload)
    merged.update(extras)
    return merged


def ids_of(rows: List[Json]) -> List[str]:
    """The `id` of every row in a list response, in the order returned."""
    return [row["id"] for row in rows]


def field_of(rows: List[Json], field: str) -> List[Any]:
    """One field of every row in a list response, in the order returned."""
    return [row[field] for row in rows]
