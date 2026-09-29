"""The two calculations that publish a different number under each of their variants:
the fire potential index and the net-benefit accounting."""

from test_helpers.assertions import (
    assert_2dp,
    assert_4dp,
    assert_append_only_record,
    assert_effective_inputs,
    assert_fpi,
    assert_instant,
    assert_integer,
    assert_net_benefit,
)
from test_helpers.fixtures import (
    RESTORE_ALPHA_AT,
    RESTORE_BRAVO_AT,
    RESTORE_CHARLIE_AT,
    build_alpha_station_network,
    build_patrolled_event,
    compute_index,
    file_observation,
    move_clock,
    re_energize,
    read_circuit,
    read_event,
    register_circuit,
    register_station,
)
from test_helpers.types import ComputationVariant, HftdTier, TelemetryStatus


def _alpha_with_two_stations():
    """ALPHA and the four observations that straddle the 2026-08-15 window."""
    alpha = register_circuit(
        circuit_code="ALPHA",
        district_code="D-NORTH",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=7.0,
        equipment_condition_index=55,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    build_alpha_station_network(alpha["id"])
    return alpha


def _juliet_with_one_observation_per_station():
    """JULIET, where each station holds exactly one in-window observation, so the two
    variants select identical values and only the rounding rule can differ."""
    juliet = register_circuit(
        circuit_code="JULIET",
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=7.0,
        equipment_condition_index=55,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    ws_j1 = register_station(
        juliet["id"],
        station_code="WS-J1",
        elevation_ft=3100,
        representativeness_weight=0.70,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    ws_j2 = register_station(
        juliet["id"],
        station_code="WS-J2",
        elevation_ft=2500,
        representativeness_weight=0.45,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        ws_j1["id"],
        "2026-08-14T18:00:00Z",
        wind_gust_mph=62.0,
        relative_humidity_pct=22.0,
        temperature_f=104.0,
        dead_fuel_moisture_pct=8.0,
    )
    file_observation(
        ws_j2["id"],
        "2026-08-14T17:00:00Z",
        wind_gust_mph=48.0,
        relative_humidity_pct=26.0,
        temperature_f=101.0,
        dead_fuel_moisture_pct=9.0,
    )
    return juliet


# --------------------------------------------------------------------------
# The envelope reduction against the latest-observation reduction
# --------------------------------------------------------------------------
def test_forecast_envelope_and_validated_latest_diverge_by_seven_points():
    """One observation set scored twice: the worst-case envelope reads 85.93 and the
    latest-observation reduction reads 78.69.

    "Under `FORECAST` the reduction is a worst-case envelope across the station's
    in-window observations: the greatest `wind_gust_mph`, the smallest
    `relative_humidity_pct`, and the smallest `dead_fuel_moisture_pct`, each taken
    independently and therefore possibly from three different observations."

    Design: Difficulty/dual_variant_calc/fpi_forecast_envelope_vs_validated_latest_divergence
    """
    alpha = _alpha_with_two_stations()

    forecast = compute_index(alpha["id"], "2026-08-15", ComputationVariant.FORECAST.value)
    validated = compute_index(
        alpha["id"], "2026-08-15", ComputationVariant.VALIDATED.value
    )

    assert_append_only_record(forecast)
    assert_integer(forecast["contributing_station_count"], 2)
    assert_effective_inputs(forecast, 56.5, 23.6, 8.4)
    assert_fpi(forecast, 85.93, "R5")

    assert_integer(validated["contributing_station_count"], 2)
    assert_fpi(validated, 78.69, "R5")

    assert_2dp(
        round(forecast["fpi_score"] - validated["fpi_score"], 2),
        7.24,
    )


def test_validated_index_does_not_overwrite_the_circuit_forecast_summary():
    """The after-action row leaves the circuit reading its forecast score and EXTREME.

    "A `VALIDATED` row never moves the posture — it exists purely as the after-action
    record for regulatory reporting."

    Design: Difficulty/dual_variant_calc/fpi_forecast_envelope_vs_validated_latest_divergence
    """
    alpha = _alpha_with_two_stations()

    compute_index(alpha["id"], "2026-08-15", ComputationVariant.FORECAST.value)
    after_forecast = read_circuit(alpha["id"])
    assert_2dp(after_forecast["latest_forecast_fpi_score"], 85.93)
    assert after_forecast["latest_forecast_fpi_tier"] == "R5"
    assert after_forecast["risk_posture"] == "EXTREME"

    compute_index(alpha["id"], "2026-08-15", ComputationVariant.VALIDATED.value)
    after_validated = read_circuit(alpha["id"])

    assert_2dp(after_validated["latest_forecast_fpi_score"], 85.93)
    assert after_validated["latest_forecast_fpi_tier"] == "R5"
    assert after_validated["risk_posture"] == "EXTREME"


# --------------------------------------------------------------------------
# The intermediate-rounding rule isolated from the reduction rule
# --------------------------------------------------------------------------
def test_one_observation_per_station_isolates_the_forecast_intermediate_rounding():
    """With identical reduced values the variants still part at the fourth digit:
    85.93 against 85.97.

    "Under `FORECAST`, each blended value is rounded half up to one decimal place
    *before* the components are computed, and the rounded numbers are what
    `effective_wind_gust_mph`, `effective_relative_humidity_pct`, and
    `effective_dead_fuel_moisture_pct` report."

    Design: Difficulty/dual_variant_calc/fpi_variant_intermediate_rounding_isolated
    """
    juliet = _juliet_with_one_observation_per_station()

    forecast = compute_index(juliet["id"], "2026-08-15", ComputationVariant.FORECAST.value)
    validated = compute_index(
        juliet["id"], "2026-08-15", ComputationVariant.VALIDATED.value
    )

    assert_integer(forecast["contributing_station_count"], 2)
    assert_integer(validated["contributing_station_count"], 2)
    assert_2dp(forecast["fpi_score"], 85.93)
    assert_2dp(validated["fpi_score"], 85.97)
    assert forecast["fpi_score"] != validated["fpi_score"], (
        "the two variants must not publish the same score"
    )


def test_forecast_components_are_computed_from_the_rounded_blend():
    """The rounded blend of 56.5 and 23.6 and 8.4 yields wind 91.25 and dryness 90.8.

    "Under `VALIDATED`, the blended values are carried at full precision into the
    components with no intermediate rounding."

    Design: Difficulty/dual_variant_calc/fpi_variant_intermediate_rounding_isolated
    """
    juliet = _juliet_with_one_observation_per_station()

    forecast = compute_index(juliet["id"], "2026-08-15", ComputationVariant.FORECAST.value)

    assert_effective_inputs(forecast, 56.5, 23.6, 8.4)
    assert_2dp(forecast["wind_component"], 91.25)
    assert_2dp(forecast["dryness_component"], 90.8)
    assert_2dp(forecast["terrain_component"], 100)
    assert_2dp(forecast["equipment_component"], 45)
    assert_2dp(forecast["fpi_score"], 85.93)


# --------------------------------------------------------------------------
# The forecast outage window against the realised one
# --------------------------------------------------------------------------
def test_pre_event_accounting_measures_the_forecast_window():
    """Before restoration the event reports the 24-hour forecast window: impact 45.60
    and ratio 0.3395.

    "Under `PRE_EVENT` — the default from scope determination until
    `actual_restored_at` is stamped, and the variant the arming threshold reads — the
    window runs from `forecast_onset_at` to `forecast_all_clear_at`, so
    `duration_hours` is the *forecast* outage length and the counts are the scope-time
    snapshots."

    Design: Difficulty/dual_variant_calc/net_benefit_pre_event_vs_post_event_window
    """
    ctx = build_patrolled_event()

    event = read_event(ctx["event_id"])

    assert_net_benefit(
        event,
        variant="PRE_EVENT",
        duration_hours=24,
        customer_impact_score=45.60,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=45.60,
        ignition_risk_avoided_score=15.48,
        net_benefit_ratio=0.3395,
    )
    assert event["actual_restored_at"] is None


def test_last_restoration_switches_the_accounting_to_the_realised_window():
    """Stamping the realised restoration at 04:30Z re-runs the accounting over 34
    ceilinged hours: impact 64.60 and ratio 0.2396.

    "Under `POST_EVENT` — computed once `actual_restored_at` is stamped, and frozen at
    close — the window runs from `actual_de_energized_at` to `actual_restored_at`, so
    `duration_hours` is the *realised* outage length including all the patrol and
    restoration time."

    Design: Difficulty/dual_variant_calc/net_benefit_pre_event_vs_post_event_window
    """
    ctx = build_patrolled_event()

    move_clock(RESTORE_ALPHA_AT)
    re_energize(ctx["alpha"]["id"])
    move_clock(RESTORE_BRAVO_AT)
    re_energize(ctx["bravo"]["id"])

    still_pre_event = read_event(ctx["event_id"])
    assert_net_benefit(
        still_pre_event,
        variant="PRE_EVENT",
        duration_hours=24,
        customer_impact_score=45.60,
        net_benefit_ratio=0.3395,
    )

    move_clock(RESTORE_CHARLIE_AT)
    re_energize(ctx["charlie"]["id"])

    event = read_event(ctx["event_id"])
    assert_instant(event["actual_de_energized_at"], "2026-08-15T19:00:00Z")
    assert_instant(event["actual_restored_at"], "2026-08-17T04:30:00Z")
    assert_net_benefit(
        event,
        variant="POST_EVENT",
        duration_hours=34,
        customer_impact_score=64.60,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=64.60,
        ignition_risk_avoided_score=15.48,
        net_benefit_ratio=0.2396,
    )
    assert_4dp(event["net_benefit_ratio"], 0.2396)
