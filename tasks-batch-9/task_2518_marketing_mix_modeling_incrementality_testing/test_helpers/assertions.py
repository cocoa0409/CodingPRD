"""Reusable shape and invariant checks.

Two kinds of helper live here. The first kind asserts that a row carries the
fields the contract declares for its entity, with the declared value domains and
the declared decimal precision. The second kind asserts the contract's stated
invariants — the two conserved quantities, the list ordering rule, the pagination
envelope and the power step table — so that a test can state the interesting part
of its claim in one line and still check the surrounding guarantees.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as k
from .types import Json, JsonList, PageMeta

# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_request_meta(meta: Dict[str, Any]) -> None:
    """Every response carries a correlation id and a server timestamp."""
    assert isinstance(meta.get("api_request_id"), str), meta
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta


def assert_common_fields(row: Json, expected_version: Optional[int] = None) -> None:
    """Identity, both timestamps and the mutation counter every row carries."""
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int), row["version"]
    assert row["version"] >= 1, row["version"]
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_page_meta(
    meta: PageMeta,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """The four pagination members, with optional exact expectations."""
    assert isinstance(meta["limit"], int) and meta["limit"] >= k.MIN_LIMIT, meta
    assert meta["limit"] <= k.MAX_LIMIT, meta
    assert isinstance(meta["offset"], int) and meta["offset"] >= 0, meta
    assert isinstance(meta["total_count"], int) and meta["total_count"] >= 0, meta
    assert isinstance(meta["has_more"], bool), meta
    if limit is not None:
        assert meta["limit"] == limit, meta
    if offset is not None:
        assert meta["offset"] == offset, meta
    if total_count is not None:
        assert meta["total_count"] == total_count, meta
    if has_more is not None:
        assert meta["has_more"] is has_more, meta


# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


def assert_decimal_places(value: Any, places: int, label: str = "value") -> None:
    """A numeric answer carries exactly the declared number of decimal places."""
    assert value is not None, f"{label} is null"
    quantised = Decimal(str(value)).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )
    assert Decimal(str(value)) == quantised, (
        f"{label} {value!r} is not expressible in {places} decimal places"
    )


def assert_percentage(value: Any, label: str = "percentage") -> None:
    assert_decimal_places(value, k.DECIMALS_PERCENTAGE, label)


def assert_unit_quantity(value: Any, label: str = "unit quantity") -> None:
    assert_decimal_places(value, k.DECIMALS_UNIT_QUANTITY, label)


def assert_cents(value: Any, label: str = "cents") -> None:
    """Money is always an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def assert_created_at_ascending(rows: JsonList) -> None:
    """List results are always ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"created_at not ascending: {stamps}"


def assert_ordered_by(rows: JsonList, field: str) -> None:
    """Rows are ascending in the named field."""
    values = [row[field] for row in rows]
    assert values == sorted(values), f"{field} not ascending: {values}"


def assert_not_ordered_by_id(rows: JsonList) -> None:
    """A row's id is never a sort key; two rows suffice to see a mistake."""
    if len(rows) < 2:
        return
    ids = [row["id"] for row in rows]
    assert ids != sorted(ids) or [r["created_at"] for r in rows] == sorted(
        r["created_at"] for r in rows
    ), "ordering appears to follow id rather than created_at"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


def assert_market(row: Json) -> None:
    assert_common_fields(row)
    assert isinstance(row["market_code"], str)
    assert isinstance(row["name"], str)
    assert isinstance(row["total_population"], int)
    assert_cents(row["annual_budget_ceiling_cents"], "annual_budget_ceiling_cents")
    assert isinstance(row["currency_code"], str) and len(row["currency_code"]) == 3
    assert isinstance(row["celled_population"], int)
    assert isinstance(row["held_out_population"], int)
    assert_percentage(row["held_out_population_pct"], "held_out_population_pct")
    assert row["data_posture"] in k.DATA_POSTURES, row["data_posture"]
    assert "published_model_run_id" in row


def assert_media_channel(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert isinstance(row["channel_code"], str)
    assert row["channel_type"] in k.CHANNEL_TYPES, row["channel_type"]
    assert_decimal_places(row["adstock_decay_rate"], 2, "adstock_decay_rate")
    assert 0.0 <= row["adstock_decay_rate"] <= 0.95
    assert 0 <= row["adstock_max_lag_periods"] <= 8
    assert row["saturation_half_point_cents"] > 0
    assert row["response_ceiling_units"] >= 0
    assert row["min_spend_cents"] >= 0
    assert row["max_spend_cents"] >= row["min_spend_cents"]
    assert row["status"] in k.CHANNEL_STATUSES, row["status"]


def assert_geo_cell(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert isinstance(row["cell_code"], str)
    assert row["population"] > 0
    assert row["assignment_state"] in k.CELL_ASSIGNMENT_STATES, row["assignment_state"]
    assert "assigned_experiment_id" in row
    assert "washout_until_date" in row


def assert_data_window(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert row["window_end_date"] > row["window_start_date"]
    assert row["granularity"] in k.GRANULARITIES, row["granularity"]
    assert isinstance(row["expected_period_count"], int)
    assert isinstance(row["sales_period_count"], int)
    assert isinstance(row["spend_observation_count"], int)
    assert_percentage(row["lag_completeness_pct"], "lag_completeness_pct")
    assert row["status"] in k.WINDOW_STATUSES, row["status"]
    assert isinstance(row["reopen_count"], int)


def assert_spend_observation(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["data_window_id"])
    assert is_valid_uuid(row["channel_id"])
    assert_cents(row["spend_cents"], "spend_cents")
    assert row["spend_cents"] >= 0
    assert row["impressions"] >= 0
    assert isinstance(row["is_restatement"], bool)
    assert "superseded_by_id" in row
    assert isinstance(row["data_window_version_after"], int)


def assert_sales_observation(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["data_window_id"])
    assert row["units_sold"] > 0
    assert_cents(row["revenue_cents"], "revenue_cents")
    assert_cents(row["avg_price_cents"], "avg_price_cents")


def assert_model_run(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert is_valid_uuid(row["data_window_id"])
    assert isinstance(row["included_channel_ids"], list)
    assert 1 <= len(row["included_channel_ids"]) <= 8
    assert len(set(row["included_channel_ids"])) == len(row["included_channel_ids"])
    assert isinstance(row["control_variables"], list)
    assert set(row["control_variables"]) <= set(k.CONTROL_VARIABLES)
    assert row["seasonality_mode"] in k.SEASONALITY_MODES, row["seasonality_mode"]
    assert row["carryover_attribution_mode"] in k.CARRYOVER_MODES
    assert row["holdout_periods"] >= 1
    assert row["fit_status"] in k.FIT_STATUSES, row["fit_status"]
    assert row["validation_status"] in k.VALIDATION_STATUSES, row["validation_status"]
    assert row["calibration_status"] in k.CALIBRATION_STATUSES, row["calibration_status"]
    assert row["publication_status"] in k.PUBLICATION_STATUSES, row["publication_status"]


def assert_run_state(
    row: Json,
    fit_status: str,
    validation_status: str,
    calibration_status: str,
    publication_status: str,
) -> None:
    """All four parallel state dimensions of a run at once."""
    actual = (
        row["fit_status"],
        row["validation_status"],
        row["calibration_status"],
        row["publication_status"],
    )
    expected = (fit_status, validation_status, calibration_status, publication_status)
    assert actual == expected, f"expected run state {expected}, got {actual}"


def assert_channel_contribution(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["model_run_id"])
    assert is_valid_uuid(row["channel_id"])
    assert row["attribution_mode_used"] in k.CARRYOVER_MODES
    assert isinstance(row["adstocked_spend_series"], list)
    assert_cents(row["mean_adstocked_spend_cents"], "mean_adstocked_spend_cents")
    assert_unit_quantity(row["contribution_units"], "contribution_units")
    assert_unit_quantity(
        row["calibrated_contribution_units"], "calibrated_contribution_units"
    )
    assert_cents(row["contribution_revenue_cents"], "contribution_revenue_cents")
    assert_cents(
        row["calibrated_contribution_revenue_cents"],
        "calibrated_contribution_revenue_cents",
    )
    assert_cents(row["attributed_spend_cents"], "attributed_spend_cents")
    assert_decimal_places(row["average_roi"], k.DECIMALS_UNIT_QUANTITY, "average_roi")
    assert_decimal_places(
        row["marginal_roi"], k.DECIMALS_MARGINAL_ROI, "marginal_roi"
    )
    assert_percentage(row["ci_half_width_pct"], "ci_half_width_pct")
    assert_unit_quantity(row["ci_low_units"], "ci_low_units")
    assert_unit_quantity(row["ci_high_units"], "ci_high_units")
    assert isinstance(row["is_current"], bool)
    assert row["ci_low_units"] <= row["ci_high_units"]


def assert_experiment(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert is_valid_uuid(row["channel_id"])
    assert row["design_type"] in k.DESIGN_TYPES, row["design_type"]
    assert row["readout_method"] in k.READOUT_METHODS, row["readout_method"]
    assert row["end_date"] > row["start_date"]
    assert 0 <= row["washout_days"] <= 60
    assert 0.0 < row["minimum_detectable_effect_pct"] <= 100.0
    assert_decimal_places(
        row["minimum_detectable_effect_pct"], 1, "minimum_detectable_effect_pct"
    )
    assert 0.0 < row["baseline_conversion_rate"] < 1.0
    assert row["planned_treatment_population"] > 0
    assert row["planned_control_population"] > 0
    assert isinstance(row["treatment_population"], int)
    assert isinstance(row["control_population"], int)
    assert row["status"] in k.EXPERIMENT_STATUSES, row["status"]
    assert isinstance(row["redesign_count"], int)
    if row["power_index"] is not None:
        assert_unit_quantity(row["power_index"], "power_index")
    if row["computed_power"] is not None:
        assert_unit_quantity(row["computed_power"], "computed_power")
    if row["measured_lift_pct"] is not None:
        assert_percentage(row["measured_lift_pct"], "measured_lift_pct")
    if row["synthetic_control_weight"] is not None:
        assert_decimal_places(
            row["synthetic_control_weight"],
            k.DECIMALS_SYNTHETIC_WEIGHT,
            "synthetic_control_weight",
        )


def assert_draft_experiment_fields_cleared(row: Json) -> None:
    """A draft — new or reworked — carries no power, no counts and no lift."""
    for field in (
        "power_index",
        "computed_power",
        "treatment_conversions",
        "control_conversions",
        "pre_treatment_conversions",
        "pre_control_conversions",
        "measured_lift_pct",
        "lift_ci_half_width_pct",
        "lift_ci_low_pct",
        "lift_ci_high_pct",
    ):
        assert row[field] is None, f"{field} should be null in DRAFT, got {row[field]!r}"
    assert row["treatment_population"] == 0, row["treatment_population"]
    assert row["control_population"] == 0, row["control_population"]


def assert_calibration_record(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["model_run_id"])
    assert is_valid_uuid(row["channel_id"])
    assert is_valid_uuid(row["experiment_id"])
    assert_percentage(row["experiment_lift_pct"], "experiment_lift_pct")
    assert_unit_quantity(row["model_implied_lift_pct"], "model_implied_lift_pct")
    assert_unit_quantity(row["calibration_multiplier"], "calibration_multiplier")
    assert (
        k.CALIBRATION_MULTIPLIER_FLOOR
        <= row["calibration_multiplier"]
        <= k.CALIBRATION_MULTIPLIER_CEILING
    ), row["calibration_multiplier"]
    assert row["bias_direction"] in k.BIAS_DIRECTIONS, row["bias_direction"]
    assert isinstance(row["superseded"], bool)
    assert isinstance(row["model_run_version_after"], int)


def assert_budget_scenario(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["market_id"])
    assert is_valid_uuid(row["model_run_id"])
    assert row["total_budget_cents"] > 0
    assert row["planning_end_date"] > row["planning_start_date"]
    assert isinstance(row["planning_period_count"], int)
    assert_percentage(row["reallocation_fee_pct"], "reallocation_fee_pct")
    for field in (
        "reallocation_fee_cents",
        "allocated_total_cents",
        "unallocated_cents",
        "shifted_total_cents",
        "projected_incremental_revenue_cents",
    ):
        assert_cents(row[field], field)
    assert_unit_quantity(
        row["projected_contribution_units"], "projected_contribution_units"
    )
    assert row["status"] in k.SCENARIO_STATUSES, row["status"]


def assert_budget_allocation(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["budget_scenario_id"])
    assert is_valid_uuid(row["channel_id"])
    for field in ("baseline_spend_cents", "allocated_cents", "shifted_cents"):
        assert_cents(row[field], field)
    assert_unit_quantity(
        row["projected_contribution_units"], "projected_contribution_units"
    )
    assert row["constraint_binding"] in k.CONSTRAINT_BINDINGS, row["constraint_binding"]


def assert_reconciliation_report(row: Json) -> None:
    assert_common_fields(row)
    assert is_valid_uuid(row["model_run_id"])
    assert row["reporting_period_end"] > row["reporting_period_start"]
    assert isinstance(row["variance_lines"], list) and row["variance_lines"]
    for line in row["variance_lines"]:
        assert is_valid_uuid(line["channel_id"])
        assert_cents(line["model_cents"], "model_cents")
        assert_cents(line["platform_revenue_cents"], "platform_revenue_cents")
        assert_cents(line["variance_cents"], "variance_cents")
        assert_percentage(line["variance_pct"], "variance_pct")
        assert (
            line["variance_cents"]
            == line["platform_revenue_cents"] - line["model_cents"]
        )
    for field in (
        "platform_reported_revenue_cents",
        "model_attributed_revenue_cents",
        "total_variance_cents",
    ):
        assert_cents(row[field], field)
    assert_percentage(row["weighted_variance_pct"], "weighted_variance_pct")
    assert row["attribution_gap_flag"] in ("MATERIAL", "IMMATERIAL")
    assert row["basis"] in k.REPORT_BASES, row["basis"]
    assert row["status"] in k.REPORT_STATUSES, row["status"]
    # The three totals are exact integer sums over the lines, with no rounding.
    assert row["platform_reported_revenue_cents"] == sum(
        line["platform_revenue_cents"] for line in row["variance_lines"]
    )
    assert row["model_attributed_revenue_cents"] == sum(
        line["model_cents"] for line in row["variance_lines"]
    )
    assert row["total_variance_cents"] == sum(
        line["variance_cents"] for line in row["variance_lines"]
    )


# ---------------------------------------------------------------------------
# The two conserved quantities
# ---------------------------------------------------------------------------


def assert_budget_conservation(scenario: Json) -> None:
    """The scenario's three cent buckets always add up to the whole budget."""
    total = (
        scenario["allocated_total_cents"]
        + scenario["reallocation_fee_cents"]
        + scenario["unallocated_cents"]
    )
    assert total == scenario["total_budget_cents"], (
        "allocated_total_cents + reallocation_fee_cents + unallocated_cents "
        f"== {total}, but total_budget_cents == {scenario['total_budget_cents']}"
    )


def assert_holdout_conservation(market: Json, cells: JsonList) -> None:
    """held_out_population equals the population of the enlisted cells."""
    enlisted = sum(
        cell["population"]
        for cell in cells
        if cell["assignment_state"] in ("TREATMENT", "CONTROL", "WASHOUT")
    )
    assert market["held_out_population"] == enlisted, (
        f"held_out_population {market['held_out_population']} does not match the "
        f"{enlisted} enlisted in TREATMENT, CONTROL or WASHOUT"
    )


def assert_celled_population(market: Json, cells: JsonList) -> None:
    """celled_population counts every cell of the market, whatever its state."""
    total = sum(cell["population"] for cell in cells)
    assert market["celled_population"] == total, (
        f"celled_population {market['celled_population']} != {total}"
    )


def assert_baseline_identity(run: Json, contributions: JsonList) -> None:
    """modeled_sales_units splits exactly into baseline plus the contributions."""
    attributed = sum(
        Decimal(str(row["contribution_units"])) for row in contributions
    )
    expected = Decimal(str(run["modeled_sales_units"])) - attributed
    assert Decimal(str(run["baseline_sales_units"])) == expected, (
        f"baseline_sales_units {run['baseline_sales_units']} does not close the "
        f"identity; expected {expected}"
    )


def assert_calibrated_baseline_identity(run: Json, contributions: JsonList) -> None:
    """After a recalibration the identity closes over the calibrated units."""
    attributed = sum(
        Decimal(str(row["calibrated_contribution_units"])) for row in contributions
    )
    expected = Decimal(str(run["modeled_sales_units"])) - attributed
    assert Decimal(str(run["baseline_sales_units"])) == expected, (
        f"baseline_sales_units {run['baseline_sales_units']} does not close the "
        f"calibrated identity; expected {expected}"
    )


# ---------------------------------------------------------------------------
# The power step table
# ---------------------------------------------------------------------------


def expected_power_for(power_index: float) -> float:
    """The step the table assigns to an index; upper bounds are strict."""
    value = Decimal(str(power_index))
    for upper, power in k.POWER_STEP_TABLE:
        if value < Decimal(str(upper)):
            return power
    return k.POWER_TOP_STEP


def assert_power_step(experiment: Json) -> None:
    """computed_power is the step the frozen power_index selects."""
    assert experiment["power_index"] is not None, "power_index not frozen"
    expected = expected_power_for(experiment["power_index"])
    assert Decimal(str(experiment["computed_power"])) == Decimal(str(expected)), (
        f"power_index {experiment['power_index']} should select {expected}, "
        f"got {experiment['computed_power']}"
    )


# ---------------------------------------------------------------------------
# Small helpers used by many tests
# ---------------------------------------------------------------------------


def rows_by(rows: JsonList, field: str) -> Dict[Any, Json]:
    """Index a list response by one of its fields."""
    return {row[field]: row for row in rows}


def only(rows: Sequence[Json]) -> Json:
    """Assert a list response holds exactly one row and return it."""
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    return rows[0]


def assert_same_row(before: Json, after: Json, *fields: str) -> None:
    """The named fields did not move between two reads of the same row."""
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_version_unchanged(before: Json, after: Json) -> None:
    """A refused mutation must not bump the version counter."""
    assert before["version"] == after["version"], (
        f"version moved from {before['version']} to {after['version']} on a "
        "request that should have changed nothing"
    )


def series_of(contribution: Json) -> List[int]:
    """The adstocked spend series of a contribution row."""
    return list(contribution["adstocked_spend_series"])
