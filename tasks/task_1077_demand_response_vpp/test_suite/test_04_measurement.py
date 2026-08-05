"""Baseline measurement (dual variant) and the completion measurement cascade.

Queue A: baseline_ten_of_ten_vs_weather_regression,
event_complete_measurement_cascade.
"""
import pytest

from test_helpers import (
    validate_success, TEST_USERS,
    setup_completed_single_device_event,
)

OP = TEST_USERS["program_operator_headers"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / baseline_ten_of_ten_vs_weather_regression
# --------------------------------------------------------------------------- #
def test_baseline_ten_of_ten_is_mean_of_top_three(api):
    """PRD §3.6: "Under TEN_OF_TEN, the lookback readings are sorted by kw_load
    descending, ties broken by interval_start descending, the top three are
    selected, and baseline_kw is the arithmetic mean of those three kw_load
    values."

    Design: Difficulty/dual_variant_calc/baseline_ten_of_ten_vs_weather_regression
    """
    ctx = setup_completed_single_device_event(
        baseline_method="TEN_OF_TEN", baseline_loads=(10, 9, 8), event_load=4.0)
    assert ctx["disp"]["baseline_kw"] == pytest.approx(9.0, abs=0.001)


def test_baseline_weather_regression_is_scaled_mean(api):
    """PRD §3.6: "Under WEATHER_REGRESSION, the top-N selection is not used at all:
    baseline_kw is the arithmetic mean of the kw_load values across all readings
    in the lookback, multiplied by a weather adjustment factor of 1.10."

    Design: Difficulty/dual_variant_calc/baseline_ten_of_ten_vs_weather_regression
    """
    ctx = setup_completed_single_device_event(
        baseline_method="WEATHER_REGRESSION", baseline_loads=(10, 9, 8), event_load=4.0)
    # mean(10,9,8) = 9.0 -> * 1.10 = 9.9, diverging from the TEN_OF_TEN 9.0.
    assert ctx["disp"]["baseline_kw"] == pytest.approx(9.9, abs=0.001)


# --------------------------------------------------------------------------- #
# transitive_cascade / event_complete_measurement_cascade
# --------------------------------------------------------------------------- #
def test_complete_computes_dispatch_delivered_kwh(api):
    """PRD §3.6: "The delivered_kwh is actual_reduction_kw multiplied by the event
    duration in hours, rounded half-up to three decimal places."

    Design: Difficulty/transitive_cascade/event_complete_measurement_cascade
    """
    ctx = setup_completed_single_device_event(
        baseline_method="TEN_OF_TEN", baseline_loads=(10, 9, 8), event_load=4.0)
    # baseline 9.0, avg load 4.0 -> actual 5.0 kW * 2 h = 10.0 kWh (hop 1)
    assert ctx["disp"]["delivered_kwh"] == pytest.approx(10.0, abs=0.001)


def test_complete_cascades_season_delivered_to_enrollment_and_aggregator(api):
    """PRD §3.6: "In the second stage, because each measured dispatch has reached
    COMPLETED, its delivered_kwh is added into the owning enrollment's
    season_delivered_kwh. In the third stage, because those enrollment totals
    changed, each affected aggregator's season_delivered_kwh is recomputed as the
    sum of season_delivered_kwh over that aggregator's enrollments."

    Design: Difficulty/transitive_cascade/event_complete_measurement_cascade
    """
    ctx = setup_completed_single_device_event(
        baseline_method="TEN_OF_TEN", baseline_loads=(10, 9, 8), event_load=4.0)
    enr = validate_success(api.get_enrollment(ctx["enr_id"], OP))
    assert enr["season_delivered_kwh"] == pytest.approx(10.0, abs=0.001), "hop 2 (enrollment)"
    agg = validate_success(api.get_aggregator(ctx["agg_id"], OP))
    assert agg["season_delivered_kwh"] == pytest.approx(10.0, abs=0.001), "hop 3 (aggregator)"
