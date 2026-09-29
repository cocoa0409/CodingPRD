"""Values placed exactly on a cut-point, a threshold, a lead-time floor and a window
endpoint, together with the neighbour one step to the other side."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_NOTIFICATION_LEAD_TIME_SHORT,
    ERR_OBSERVATION_WINDOW_EMPTY,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_4dp,
    assert_batch_outcome,
    assert_circuit_state,
    assert_effective_inputs,
    assert_event_dimensions,
    assert_fpi,
    assert_fpi_components,
    assert_impact_counts,
    assert_instant,
    assert_integer,
    assert_net_benefit,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.fixtures import (
    ADVANCE_SEND_AT,
    arm_event,
    build_scoped_event,
    compute_index,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    plan_batch,
    read_batch,
    read_circuit,
    read_event,
    read_records,
    read_scope_rows,
    register_circuit,
    register_customer,
    register_station,
    scope_event,
)
from test_helpers.test_users import ANALYST_HEADERS, LIAISON_HEADERS
from test_helpers.types import (
    ComputationVariant,
    CustomerClass,
    HftdTier,
    NotificationStage,
    TelemetryStatus,
)

BOUNDARY_OBSERVED_AT = "2026-08-31T12:00:00Z"
BOUNDARY_FORECAST_DATE = "2026-09-01"
HOTEL_FORECAST_DATE = "2026-08-20"
HOTEL_ONSET_AT = "2026-08-20T06:00:00Z"
HOTEL_ALL_CLEAR_AT = "2026-08-20T18:00:00Z"
HOTEL_ADVANCE_SEND_AT = "2026-08-18T06:00:00Z"
LATE_SEND_AT = "2026-08-13T18:01:00Z"
INDIA_FORECAST_DATE = "2026-08-15"
INDIA_WINDOW_CLOSE_AT = "2026-08-16T00:00:00Z"
INDIA_WINDOW_OPEN_AT = "2026-08-14T00:00:00Z"


def _dry_circuit(circuit_code, station_code, wind_gust_mph):
    """A TIER_2 circuit on 6.0 overhead miles whose single station reports very dry
    fuels, so only the gust separates one such circuit from another."""
    circuit = register_circuit(
        circuit_code=circuit_code,
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=6.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        circuit["id"],
        station_code=station_code,
        elevation_ft=2400,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        BOUNDARY_OBSERVED_AT,
        wind_gust_mph=wind_gust_mph,
        relative_humidity_pct=10.0,
        temperature_f=103.0,
        dead_fuel_moisture_pct=6.0,
    )
    return circuit


def _hotel_scoped_event():
    """HOTEL over a 12-hour window: two accounts, an index of 60.00, and an ignition term
    of 4.80 against an impact of 19.20."""
    hotel = register_circuit(
        circuit_code="HOTEL",
        district_code="D-SOUTH",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=8.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        hotel["id"],
        station_code="WS-H1",
        elevation_ft=2000,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        "2026-08-19T12:00:00Z",
        wind_gust_mph=52.0,
        relative_humidity_pct=62.0,
        temperature_f=94.0,
        dead_fuel_moisture_pct=9.0,
    )
    index = compute_index(
        hotel["id"], HOTEL_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    register_customer(
        hotel["id"],
        account_number="ACC-H1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=["VOICE"],
        address_zone_code="ZH",
    )
    register_customer(
        hotel["id"],
        account_number="ACC-H2",
        medical_baseline=True,
        notification_channels=["SMS"],
        address_zone_code="ZH",
    )
    event = open_event(
        index["id"],
        onset_at=HOTEL_ONSET_AT,
        all_clear_at=HOTEL_ALL_CLEAR_AT,
        event_code="EV-H",
    )
    scoped = scope_event(event["id"], event["version"])
    return hotel, index, scoped


def _india_circuit_with_boundary_observation():
    """INDIA's only observation sits exactly on the closing boundary of the 2026-08-15
    selection window."""
    india = register_circuit(
        circuit_code="INDIA",
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=6.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        india["id"],
        station_code="WS-I1",
        elevation_ft=2400,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        INDIA_WINDOW_CLOSE_AT,
        wind_gust_mph=52.0,
        relative_humidity_pct=10.0,
        temperature_f=103.0,
        dead_fuel_moisture_pct=6.0,
    )
    return india, station


# --------------------------------------------------------------------------
# The R5 cut-point at exactly 75
# --------------------------------------------------------------------------
def test_a_score_of_exactly_seventy_five_is_tier_r5():
    """A tenth of a mile per hour of gust separates 75.00 from 74.91 and with it R5 from
    R4.

    "`fpi_tier` follows from `fpi_score` by four cut-points: below 20 is `R1`, from 20 up
    to but not including 40 is `R2`, from 40 up to but not including 60 is `R3`, from 60
    up to but not including 75 is `R4`, and 75 or above is `R5`."

    Design: Difficulty/boundary_precision_check/fpi_tier_r5_boundary_at_exactly_seventy_five
    """
    echo = _dry_circuit("ECHO", "WS-E1", 52.0)
    foxtrot = _dry_circuit("FOXTROT", "WS-F1", 51.9)

    on_the_cut_point = compute_index(
        echo["id"], BOUNDARY_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    just_below = compute_index(
        foxtrot["id"], BOUNDARY_FORECAST_DATE, ComputationVariant.FORECAST.value
    )

    assert_fpi(on_the_cut_point, 75.00, "R5")
    assert_fpi(just_below, 74.91, "R4")


def test_the_clamped_dryness_component_is_what_lands_the_score_on_the_cut_point():
    """Both circuits carry a dryness component pinned at the 100 ceiling, so the whole
    difference between the two scores comes from the wind term.

    "`dryness_component` is the effective relative humidity subtracted from 100, plus the
    quantity formed by subtracting the effective dead fuel moisture from a 12 percent
    reference and multiplying that difference by 4; the sum is then clamped to the range 0
    through 100 (note that a fuel moisture above the reference contributes a negative
    amount, which can pull the pre-clamp sum down)."

    Design: Difficulty/boundary_precision_check/fpi_tier_r5_boundary_at_exactly_seventy_five
    """
    echo = _dry_circuit("ECHO", "WS-E1", 52.0)
    foxtrot = _dry_circuit("FOXTROT", "WS-F1", 51.9)

    on_the_cut_point = compute_index(
        echo["id"], BOUNDARY_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    just_below = compute_index(
        foxtrot["id"], BOUNDARY_FORECAST_DATE, ComputationVariant.FORECAST.value
    )

    assert_fpi_components(
        on_the_cut_point, wind=80.00, dryness=100, terrain=70, equipment=20
    )
    assert_fpi_components(just_below, wind=79.75, dryness=100, terrain=70, equipment=20)
    assert_circuit_state(read_circuit(echo["id"]), risk_posture="EXTREME")
    assert_circuit_state(read_circuit(foxtrot["id"]), risk_posture="EXTREME")


# --------------------------------------------------------------------------
# The arming threshold at exactly 0.2500
# --------------------------------------------------------------------------
def test_a_ratio_of_exactly_one_quarter_clears_the_arming_gate():
    """4.80 of ignition risk against 19.20 of adjusted impact is 0.2500 to the fourth
    decimal, and the shutoff is staged.

    "And the event's `net_benefit_ratio` must be at least 0.25, or the request is refused
    with `ERR_NET_BENEFIT_BELOW_THRESHOLD`; a ratio of exactly 0.2500 clears the gate."

    Design: Difficulty/boundary_precision_check/net_benefit_ratio_exactly_at_threshold_arms
    """
    hotel, index, scoped = _hotel_scoped_event()
    assert_4dp(scoped["net_benefit_ratio"], 0.2500)

    batch = plan_batch(
        scoped["id"], NotificationStage.ADVANCE_48H.value, HOTEL_ADVANCE_SEND_AT
    )
    move_clock(HOTEL_ADVANCE_SEND_AT)
    dispatch_batch(batch["id"])

    armed = arm_event(scoped["id"])

    assert_event_dimensions(
        armed, scope_status="ARMED", notification_status="ADVANCE_SENT"
    )
    assert_net_benefit(
        armed,
        variant="PRE_EVENT",
        duration_hours=12,
        customer_impact_score=19.20,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=19.20,
        ignition_risk_avoided_score=4.80,
        net_benefit_ratio=0.2500,
    )
    assert_circuit_state(
        read_circuit(hotel["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )


def test_the_weighted_impact_base_is_what_puts_the_ratio_on_the_threshold():
    """Two accounts weigh sixteen because one is a critical facility and the other is a
    medical baseline, and sixteen over twelve hours is exactly the 19.20 the threshold
    needs.

    "The impact base is `impacted_customer_count`, plus four times
    `medical_baseline_customer_count`, plus ten times the event's `critical_facility_count`
    — a medical-baseline household counts as four ordinary accounts and a critical facility
    as ten."

    Design: Difficulty/boundary_precision_check/net_benefit_ratio_exactly_at_threshold_arms
    """
    hotel, index, scoped = _hotel_scoped_event()

    assert_fpi(index, 60.00, "R4")
    assert_scope_counts(scoped, confirmed=1, excluded=0)
    assert_impact_counts(scoped, impacted=2, medical_baseline=1, critical_facility=1)
    assert_net_benefit(
        scoped,
        duration_hours=12,
        customer_impact_score=19.20,
        crc_mitigation_credit=0.00,
        adjusted_customer_impact_score=19.20,
        net_benefit_ratio=0.2500,
    )
    rows = read_scope_rows(scoped["id"])
    assert_scope_row(
        rows, hotel["id"], fpi_score_applied=60.00, ignition_risk_term=4.80
    )


# --------------------------------------------------------------------------
# The 2,880-minute advance floor
# --------------------------------------------------------------------------
def test_a_lead_time_of_exactly_forty_eight_hours_dispatches():
    """Dispatching at 18:00Z leaves precisely 2,880 minutes to the onset and the batch
    settles.

    "A lead time strictly below the stage minimum is refused with
    `ERR_NOTIFICATION_LEAD_TIME_SHORT`; a lead time exactly equal to the minimum is
    accepted."

    Design: Difficulty/boundary_precision_check/advance_notification_lead_time_exact_minimum_accepted
    """
    ctx = build_scoped_event()
    early = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )

    move_clock(ADVANCE_SEND_AT)
    dispatched = dispatch_batch(early["id"])

    assert_integer(dispatched["lead_time_minutes"], 2880)
    assert_instant(dispatched["dispatched_at"], ADVANCE_SEND_AT)
    assert_batch_outcome(
        dispatched,
        "FAILED_PARTIAL",
        target_count=5,
        delivered_count=4,
        unreachable_count=1,
    )
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="ADVANCE_SENT"
    )


def test_one_minute_inside_the_floor_is_refused_and_writes_nothing():
    """A second batch dispatched at 18:01Z has 2,879 minutes of lead and is turned away
    with no records, no stamp and no lead time.

    "The `scheduled_send_at` the operator wrote down is a plan, not the measurement:
    `dispatched_at` is stamped from the logical clock at the moment dispatch runs, and
    `lead_time_minutes` is computed as the number of whole minutes from `dispatched_at` to
    the event's `forecast_onset_at`, floored toward negative infinity — so a dispatch that
    happens after the onset yields a negative lead time."

    Design: Difficulty/boundary_precision_check/advance_notification_lead_time_exact_minimum_accepted
    """
    ctx = build_scoped_event()
    early = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, ADVANCE_SEND_AT
    )
    late = plan_batch(
        ctx["event_id"], NotificationStage.ADVANCE_48H.value, LATE_SEND_AT
    )
    move_clock(ADVANCE_SEND_AT)
    dispatch_batch(early["id"])

    move_clock(LATE_SEND_AT)
    response = api_client.dispatch_notification_batch(late["id"], LIAISON_HEADERS)

    validate_error(response, ERR_NOTIFICATION_LEAD_TIME_SHORT, 422)
    untouched = read_batch(late["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["dispatched_at"] is None
    assert untouched["lead_time_minutes"] is None
    _, meta = read_records(notification_batch_id=late["id"])
    assert_integer(meta["total_count"], 0)
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="ADVANCE_SENT"
    )


# --------------------------------------------------------------------------
# The half-open observation window
# --------------------------------------------------------------------------
def test_an_observation_on_the_closing_boundary_leaves_the_window_empty():
    """The sole observation sits exactly 24 hours after the day anchor, which is outside,
    so no index can be computed at all.

    "`contributing_station_count` is the number of eligible stations that supplied at
    least one in-window observation; when that number is zero the computation is refused
    with `ERR_OBSERVATION_WINDOW_EMPTY`."

    Design: Difficulty/boundary_precision_check/observation_window_right_endpoint_is_exclusive
    """
    india, station = _india_circuit_with_boundary_observation()

    response = api_client.create_fire_potential_index(
        factories.fpi_payload(
            india["id"], INDIA_FORECAST_DATE, ComputationVariant.FORECAST.value
        ),
        ANALYST_HEADERS,
    )

    validate_error(response, ERR_OBSERVATION_WINDOW_EMPTY, 422)
    _, meta = validate_paginated(
        api_client.list_circuit_fire_potential_indices(india["id"], ANALYST_HEADERS)
    )
    assert_integer(meta["total_count"], 0)
    assert read_circuit(india["id"])["latest_forecast_fpi_score"] is None


def test_an_observation_on_the_opening_boundary_is_inside_the_window():
    """Filing a second observation exactly 24 hours before the anchor brings the station
    into the blend and the index scores 75.00.

    "The selection window opens 24 hours before that anchor and closes 24 hours after it
    — a 48-hour span — and it is half-open: an observation whose `observed_at` falls
    exactly on the opening boundary is inside the window, and one falling exactly on the
    closing boundary is outside it."

    Design: Difficulty/boundary_precision_check/observation_window_right_endpoint_is_exclusive
    """
    india, station = _india_circuit_with_boundary_observation()

    file_observation(
        station["id"],
        INDIA_WINDOW_OPEN_AT,
        wind_gust_mph=52.0,
        relative_humidity_pct=10.0,
        temperature_f=103.0,
        dead_fuel_moisture_pct=6.0,
    )
    index = compute_index(
        india["id"], INDIA_FORECAST_DATE, ComputationVariant.FORECAST.value
    )

    assert_integer(index["contributing_station_count"], 1)
    assert_effective_inputs(index, 52.0, 10.0, 6.0)
    assert_fpi(index, 75.00, "R5")

    refreshed = get_success_data(
        api_client.get_weather_station(station["id"], ANALYST_HEADERS)
    )
    assert_integer(refreshed["observation_count"], 2)
    assert_instant(refreshed["last_observation_at"], INDIA_WINDOW_CLOSE_AT)
    assert_2dp(read_circuit(india["id"])["latest_forecast_fpi_score"], 75.00)
