"""The arithmetic: which rows feed a computation, which constants weight them, where the
clamps and truncations bite, and which figure each derived number is read from."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_NOTIFICATION_LEAD_TIME_SHORT
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_4dp,
    assert_activation_summary,
    assert_batch_outcome,
    assert_center_state,
    assert_circuit_state,
    assert_effective_inputs,
    assert_event_dimensions,
    assert_filing_metrics,
    assert_filing_tracks,
    assert_fpi,
    assert_fpi_components,
    assert_hardening_ledger,
    assert_impact_counts,
    assert_integer,
    assert_net_benefit,
    assert_population_counters,
    assert_record,
    assert_scope_counts,
    assert_scope_row,
    record_for,
)
from test_helpers.fixtures import (
    activate_centers,
    arm_event,
    book_project,
    build_advance_dispatched_event,
    build_approved_project,
    build_armed_event,
    build_closed_event,
    build_feeder_chain,
    build_imminent_dispatched_event,
    compute_index,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    open_filing,
    plan_batch,
    read_batch,
    read_center,
    read_circuit,
    read_event,
    read_project,
    read_records,
    read_scope_rows,
    record_completion,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    scope_event,
    submit_filing,
)
from test_helpers.test_users import LIAISON_HEADERS, OFFICER_HEADERS
from test_helpers.types import (
    AccessibilityNeed,
    Channel,
    ComputationVariant,
    CustomerClass,
    HftdTier,
    Language,
    NotificationStage,
    ProgramType,
    TelemetryStatus,
)

# The 48-hour window of 2026-08-01 opens at 2026-07-31T00:00:00Z, so this instant is
# inside it and every index below is computed against the default logical clock.
BASELINE_OBSERVED_AT = "2026-07-31T12:00:00Z"
BASELINE_FORECAST_DATE = "2026-08-01"

FILTER_FORECAST_DATE = "2026-08-21"
FILTER_OBSERVED_AT = "2026-08-20T12:00:00Z"
STALE_FORECAST_DATE = "2026-08-20"
STALE_OBSERVED_AT = "2026-08-19T12:00:00Z"
FILTER_ONSET_AT = "2026-08-21T18:00:00Z"
FILTER_ALL_CLEAR_AT = "2026-08-22T18:00:00Z"

MIKE_FORECAST_DATE = "2026-09-10"
MIKE_OBSERVED_AT = "2026-09-09T12:00:00Z"
MIKE_ONSET_AT = "2026-09-10T00:00:00Z"
MIKE_ALL_CLEAR_AT = "2026-09-10T08:00:00Z"
MIKE_ADVANCE_SEND_AT = "2026-09-08T00:00:00Z"

IMMINENT_SCHEDULED_AT = "2026-08-15T17:00:00Z"
JUST_OVER_THE_HOUR = "2026-08-15T16:59:30Z"
JUST_UNDER_THE_HOUR = "2026-08-15T17:00:30Z"

FIRST_COMPLETION_DATE = "2026-06-01T00:00:00Z"
SECOND_COMPLETION_DATE = "2026-07-01T00:00:00Z"


def _scored_circuit(
    circuit_code,
    wind_gust_mph,
    relative_humidity_pct,
    dead_fuel_moisture_pct,
    forecast_date=BASELINE_FORECAST_DATE,
    observed_at=BASELINE_OBSERVED_AT,
    computation_variant=ComputationVariant.FORECAST.value,
    **circuit_overrides
):
    """One circuit, one ONLINE station of weight 1.00, one in-window observation and one
    index — so the blend is the observation itself and every component is traceable."""
    circuit = register_circuit(circuit_code=circuit_code, **circuit_overrides)
    station = register_station(
        circuit["id"],
        station_code=f"WS-{circuit_code}",
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        observed_at,
        wind_gust_mph=wind_gust_mph,
        relative_humidity_pct=relative_humidity_pct,
        dead_fuel_moisture_pct=dead_fuel_moisture_pct,
    )
    index = compute_index(circuit["id"], forecast_date, computation_variant)
    return circuit, index


def _delta_circuit():
    """A NON_HFTD circuit with 4.0 overhead miles, no weather data and no mitigation
    history — the denominator of every hardening ratio below."""
    return register_circuit(
        circuit_code="DELTA",
        district_code="D-WEST",
        hftd_tier=HftdTier.NON_HFTD.value,
        overhead_miles=4.0,
        equipment_condition_index=90,
    )


def _armed_mike_event():
    """EV-MIKE armed over an eight-hour window on TIER_2 MIKE (11.0 overhead miles, an
    R4 index of exactly 60.00) with five accounts and its 48-hour notice at 2,880
    minutes' lead."""
    mike, index = _scored_circuit(
        "MIKE",
        40.0,
        35.0,
        7.0,
        forecast_date=MIKE_FORECAST_DATE,
        observed_at=MIKE_OBSERVED_AT,
        district_code="D-WEST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=11.0,
        equipment_condition_index=80,
    )
    register_customer(
        mike["id"],
        account_number="ACC-M1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=[Channel.SMS.value],
        address_zone_code="ZM",
    )
    for ordinal in range(2, 6):
        register_customer(
            mike["id"],
            account_number=f"ACC-M{ordinal}",
            medical_baseline=True,
            notification_channels=[Channel.SMS.value],
            address_zone_code="ZM",
        )
    event = open_event(
        index["id"],
        onset_at=MIKE_ONSET_AT,
        all_clear_at=MIKE_ALL_CLEAR_AT,
        event_code="EV-MIKE",
    )
    event = scope_event(event["id"], event["version"])
    batch = plan_batch(
        event["id"], NotificationStage.ADVANCE_48H.value, MIKE_ADVANCE_SEND_AT
    )
    move_clock(MIKE_ADVANCE_SEND_AT)
    dispatch_batch(batch["id"])
    return mike, index, arm_event(event["id"])


# --------------------------------------------------------------------------
# The hardening ledger
# --------------------------------------------------------------------------
def test_undergrounding_credit_outweighs_covered_conductor_and_stops_at_unity():
    """Three underground miles on a four-mile circuit report exactly three quarters
    hardened, and the two further miles that would take the raw ratio to 1.25 report full
    hardening instead.

    "Covered conductor earns partial credit and undergrounding earns full credit: the
    numerator is `covered_conductor_miles` multiplied by 0.6 plus `underground_miles`
    multiplied by 1.0, and the denominator is the circuit's immutable `overhead_miles`."

    "That quotient is rounded half up to four decimal places and then capped at 1.0000, so
    an over-built circuit reports full hardening rather than a ratio above one."

    "The first record advances the project from `APPROVED` to `IN_EXECUTION`; further
    records that leave the cumulative total strictly below `planned_miles` keep it in
    `IN_EXECUTION`; and the record whose cumulative total lands exactly on `planned_miles`
    advances it to `COMPLETED`."

    Design: Corner/calculations/hardened_fraction_weights_undergrounding_above_covered_and_caps_at_unity
    """
    delta = _delta_circuit()
    first = build_approved_project(
        delta["id"],
        project_code="UG-1",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=9000000,
    )

    first = record_completion(
        first["id"], 3.0, FIRST_COMPLETION_DATE, read_circuit(delta["id"])["version"]
    )

    assert first["status"] == "COMPLETED"
    assert_1dp(first["completed_miles"], 3.0)
    assert_hardening_ledger(
        read_circuit(delta["id"]),
        covered_conductor_miles=0.0,
        underground_miles=3.0,
        hardened_fraction=0.7500,
    )

    second = build_approved_project(
        delta["id"],
        project_code="UG-2",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=2.0,
        unit_cost_per_mile_cents=9000000,
    )
    second = record_completion(
        second["id"], 2.0, SECOND_COMPLETION_DATE, read_circuit(delta["id"])["version"]
    )

    assert second["status"] == "COMPLETED"
    over_built = read_circuit(delta["id"])
    assert_hardening_ledger(
        over_built,
        covered_conductor_miles=0.0,
        underground_miles=5.0,
        hardened_fraction=1.0000,
    )
    assert_4dp(over_built["hardened_fraction"], 1.0000)
    assert_circuit_state(
        over_built, energization_state="ENERGIZED", risk_posture="NORMAL"
    )


# --------------------------------------------------------------------------
# The fire potential index and the posture it drives
# --------------------------------------------------------------------------
def test_the_posture_ladder_reads_the_forecast_row_and_ignores_the_validated_one():
    """An R3 forecast lifts the circuit to ELEVATED, a same-day after-action row scoring
    identically leaves it exactly there, and a circuit with no weather data at all stays at
    the bottom of the ladder.

    "If the selected index's `fpi_tier` is `R4` or `R5` the posture is `EXTREME`; if it is
    `R3` the posture is `ELEVATED`; and for `R1` or `R2` the posture is `NORMAL`."

    "If no such index exists the posture is `NORMAL` and both `latest_forecast_fpi_score`
    and `latest_forecast_fpi_tier` are null."

    "A `VALIDATED` row never moves the posture — it exists purely as the after-action
    record for regulatory reporting."

    Design: Corner/calculations/circuit_risk_posture_walks_the_tier_ladder_and_ignores_validated_rows
    """
    echo, forecast = _scored_circuit(
        "ECHO-R3",
        30.0,
        50.0,
        9.5,
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
    )
    delta = _delta_circuit()

    assert_fpi(forecast, 43.75, "R3")
    assert_fpi_components(forecast, wind=25, dryness=60, terrain=70, equipment=20)
    scored = read_circuit(echo["id"])
    assert_circuit_state(scored, risk_posture="ELEVATED")
    assert_2dp(scored["latest_forecast_fpi_score"], 43.75)
    assert scored["latest_forecast_fpi_tier"] == "R3"

    validated = compute_index(
        echo["id"], BASELINE_FORECAST_DATE, ComputationVariant.VALIDATED.value
    )

    assert_fpi(validated, 43.75, "R3")
    unmoved = read_circuit(echo["id"])
    assert_circuit_state(unmoved, risk_posture="ELEVATED")
    assert_2dp(unmoved["latest_forecast_fpi_score"], 43.75)
    assert unmoved["latest_forecast_fpi_tier"] == "R3"

    unscored = read_circuit(delta["id"])
    assert_circuit_state(unscored, risk_posture="NORMAL")
    assert unscored["latest_forecast_fpi_score"] is None
    assert unscored["latest_forecast_fpi_tier"] is None


def test_the_overdue_penalty_lands_on_the_exact_cycle_boundary():
    """Two identical circuits inspected one day apart on a one-month cycle diverge by a
    whole risk tier, because the penalty is inclusive of the instant the cycle lapses.

    "`equipment_component` is the circuit's `equipment_condition_index` subtracted from
    100, plus a 30-point penalty when the inspection cycle has lapsed, clamped to the range
    0 through 100."

    "The boolean `inspection_overdue` records whether that penalty applied: it is true when
    the circuit's `last_inspection_completed_at` is null, and also true when the logical
    clock has reached or passed `last_inspection_completed_at` advanced by the circuit's
    `inspection_cycle_months` where each cycle month is treated as exactly 30 days — so a
    circuit on the default three-year cycle is overdue 1,080 days after its last
    inspection, at the exact instant as well as after it."

    Design: Corner/calculations/fpi_inspection_overdue_penalty_applies_at_the_exact_cycle_boundary
    """
    romeo, romeo_index = _scored_circuit(
        "ROMEO",
        30.0,
        50.0,
        9.5,
        hftd_tier=HftdTier.TIER_1.value,
        overhead_miles=5.0,
        equipment_condition_index=90,
        inspection_cycle_months=1,
        last_inspection_completed_at="2026-07-02T00:00:00Z",
    )
    sierra, sierra_index = _scored_circuit(
        "SIERRA",
        30.0,
        50.0,
        9.5,
        hftd_tier=HftdTier.TIER_1.value,
        overhead_miles=5.0,
        equipment_condition_index=90,
        inspection_cycle_months=1,
        last_inspection_completed_at="2026-07-03T00:00:00Z",
    )

    assert romeo_index["inspection_overdue"] is True
    assert_fpi_components(romeo_index, equipment=40)
    assert_fpi(romeo_index, 40.75, "R3")

    assert sierra_index["inspection_overdue"] is False
    assert_fpi_components(sierra_index, equipment=10)
    assert_fpi(sierra_index, 36.25, "R2")

    assert_fpi_components(romeo_index, wind=25, dryness=60, terrain=40)
    assert_fpi_components(sierra_index, wind=25, dryness=60, terrain=40)
    assert_circuit_state(read_circuit(romeo["id"]), risk_posture="ELEVATED")
    assert_circuit_state(read_circuit(sierra["id"]), risk_posture="NORMAL")


def test_an_offline_station_is_dropped_and_a_degraded_one_counts_for_half():
    """The most extreme gust on the circuit is discarded outright while a degraded sensor
    is admitted at half weight, so the blend lands at 40.0 mph rather than anywhere near
    the 100 mph the dead sensor reported.

    "The candidate set is the circuit's stations whose `telemetry_status` is `ONLINE` or
    `DEGRADED`; `OFFLINE` stations are dropped entirely and appear in neither the numerator
    nor the denominator of any average."

    "Each remaining station gets an effective weight equal to its
    `representativeness_weight`, halved for a `DEGRADED` station and taken as-is for an
    `ONLINE` one."

    Design: Corner/calculations/fpi_drops_offline_stations_and_halves_degraded_station_weight
    """
    tango = register_circuit(
        circuit_code="TANGO",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
    )
    for code, telemetry, gust in (
        ("WS-T1", TelemetryStatus.ONLINE.value, 30.0),
        ("WS-T2", TelemetryStatus.OFFLINE.value, 100.0),
        ("WS-T3", TelemetryStatus.DEGRADED.value, 60.0),
    ):
        station = register_station(
            tango["id"],
            station_code=code,
            representativeness_weight=1.00,
            telemetry_status=telemetry,
        )
        file_observation(
            station["id"],
            BASELINE_OBSERVED_AT,
            wind_gust_mph=gust,
            relative_humidity_pct=50.0,
            dead_fuel_moisture_pct=9.5,
        )

    index = compute_index(tango["id"], BASELINE_FORECAST_DATE)

    assert_integer(index["contributing_station_count"], 2)
    assert_effective_inputs(index, gust=40.0, humidity=50.0, fuel_moisture=9.5)
    assert_fpi_components(index, wind=50, dryness=60, terrain=70, equipment=20)
    assert_fpi(index, 52.50, "R3")
    assert index["fpi_score"] != 56.88
    assert_circuit_state(read_circuit(tango["id"]), risk_posture="ELEVATED")


# --------------------------------------------------------------------------
# Scope determination as an input filter
# --------------------------------------------------------------------------
def test_scope_determination_admits_one_circuit_and_silently_drops_four():
    """A tier-R3 forecast, an after-action-only row, no forecast at all and a forecast for
    the wrong day are four distinct reasons to be left out, and none of them leaves a row
    behind.

    "A circuit is a primary candidate when its `energization_state` is `ENERGIZED`, a
    qualifying index exists for it, and that index's `fpi_tier` is `R4` or `R5`."

    "The impact base is `impacted_customer_count`, plus four times
    `medical_baseline_customer_count`, plus ten times the event's `critical_facility_count`
    — a medical-baseline household counts as four ordinary accounts and a critical facility
    as ten."

    Design: Corner/calculations/scope_determination_filters_by_variant_forecast_date_and_tier
    """
    uniform, uniform_index = _scored_circuit(
        "UNIFORM",
        40.0,
        20.0,
        3.5,
        forecast_date=FILTER_FORECAST_DATE,
        observed_at=FILTER_OBSERVED_AT,
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=5.0,
        equipment_condition_index=50,
    )
    victor, victor_index = _scored_circuit(
        "VICTOR",
        30.0,
        50.0,
        9.5,
        forecast_date=FILTER_FORECAST_DATE,
        observed_at=FILTER_OBSERVED_AT,
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
    )
    whiskey, whiskey_index = _scored_circuit(
        "WHISKEY",
        40.0,
        20.0,
        3.5,
        forecast_date=FILTER_FORECAST_DATE,
        observed_at=FILTER_OBSERVED_AT,
        computation_variant=ComputationVariant.VALIDATED.value,
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=5.0,
        equipment_condition_index=50,
    )
    xray = register_circuit(
        circuit_code="XRAY",
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=5.0,
        equipment_condition_index=50,
    )
    zulu, zulu_index = _scored_circuit(
        "ZULU",
        40.0,
        20.0,
        3.5,
        forecast_date=STALE_FORECAST_DATE,
        observed_at=STALE_OBSERVED_AT,
        hftd_tier=HftdTier.TIER_3.value,
        overhead_miles=5.0,
        equipment_condition_index=50,
    )
    register_customer(
        uniform["id"], account_number="ACC-U1", address_zone_code="ZU"
    )
    event = open_event(
        uniform_index["id"],
        onset_at=FILTER_ONSET_AT,
        all_clear_at=FILTER_ALL_CLEAR_AT,
        event_code="EV-FILTER",
    )

    scoped = scope_event(event["id"], event["version"])

    assert_fpi(uniform_index, 75.00, "R5")
    assert_fpi_components(uniform_index, dryness=100)
    assert_fpi(victor_index, 43.75, "R3")
    assert_fpi(whiskey_index, 75.00, "R5")
    assert_fpi(zulu_index, 75.00, "R5")

    assert_scope_counts(scoped, confirmed=1, excluded=0)
    rows, meta = validate_paginated(
        api_client.list_event_scopes(event["id"], OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 1)
    assert rows[0]["circuit_id"] == uniform["id"]
    assert_scope_row(
        rows,
        uniform["id"],
        scope_status="CONFIRMED",
        inclusion_basis="PRIMARY_RISK",
        fpi_score_applied=75.00,
    )
    assert_net_benefit(
        scoped,
        duration_hours=24,
        ignition_risk_avoided_score=3.75,
        customer_impact_score=2.40,
        net_benefit_ratio=1.5625,
    )
    for left_out in (victor, whiskey, xray, zulu):
        assert_circuit_state(
            read_circuit(left_out["id"]), energization_state="ENERGIZED"
        )


# --------------------------------------------------------------------------
# The notification tier ladder
# --------------------------------------------------------------------------
def test_the_critical_class_outranks_the_medical_flag_but_both_counters_move():
    """An account that is both a critical facility and a medical-baseline enrolment lands on
    the top tier and is still counted by both circuit counters.

    "Registration computes one derived field, the account's `notification_tier`, from a
    strict precedence: an account whose `customer_class` is `CRITICAL_FACILITY` is
    `TIER_A_CRITICAL`; otherwise an account whose `medical_baseline` is true is
    `TIER_B_MEDICAL`; otherwise the account is `TIER_C_STANDARD`."

    "Registration then rolls the account up onto its circuit: `customer_count` increases by
    one always, `medical_baseline_count` increases by one when `medical_baseline` is true,
    and `critical_facility_count` increases by one when `customer_class` is
    `CRITICAL_FACILITY` — so a medical-baseline critical facility increments all three."

    Design: Corner/calculations/customer_notification_tier_lets_the_critical_class_dominate_medical_baseline
    """
    alpha = register_circuit(circuit_code="ALPHA")

    both = register_customer(
        alpha["id"],
        account_number="ACC-BOTH",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        medical_baseline=True,
        notification_channels=[Channel.VOICE.value],
    )
    medical = register_customer(
        alpha["id"],
        account_number="ACC-MED",
        customer_class=CustomerClass.RESIDENTIAL.value,
        medical_baseline=True,
        notification_channels=[Channel.VOICE.value],
    )
    plain = register_customer(
        alpha["id"],
        account_number="ACC-PLAIN",
        customer_class=CustomerClass.COMMERCIAL.value,
        medical_baseline=False,
        notification_channels=[Channel.EMAIL.value],
    )

    assert both["notification_tier"] == "TIER_A_CRITICAL"
    assert medical["notification_tier"] == "TIER_B_MEDICAL"
    assert plain["notification_tier"] == "TIER_C_STANDARD"
    assert_population_counters(
        read_circuit(alpha["id"]),
        customer_count=3,
        medical_baseline_count=2,
        critical_facility_count=1,
    )


# --------------------------------------------------------------------------
# Notification routing
# --------------------------------------------------------------------------
def test_the_channel_waterfall_ignores_the_order_the_account_listed():
    """An account that wrote EMAIL first is still reached by SMS, and an account with no SMS
    consent falls through to the next channel in the fixed order.

    "Channel selection is an accessibility-filtered waterfall over a **fixed** priority
    order: `SMS` first, then `VOICE`, then `EMAIL`."

    "Targets are ordered deterministically, first by notification tier —
    `TIER_A_CRITICAL` before `TIER_B_MEDICAL` before `TIER_C_STANDARD` — and then by
    account `created_at` ascending."

    Design: Corner/calculations/notification_routing_follows_the_fixed_channel_priority_not_the_customer_order
    """
    ctx = build_feeder_chain()
    ctx["cust_a4"] = register_customer(
        ctx["alpha"]["id"],
        account_number="ACC-A4",
        customer_class=CustomerClass.RESIDENTIAL.value,
        preferred_language=Language.EN.value,
        notification_channels=[Channel.EMAIL.value, Channel.SMS.value],
        address_zone_code="Z1",
    )
    ctx = build_advance_dispatched_event(ctx)

    rows, meta = read_records(
        notification_batch_id=ctx["batch_advance"]["id"],
        customer_id=ctx["cust_a4"]["id"],
    )

    assert_integer(meta["total_count"], 1)
    assert_record(
        record_for(rows, ctx["cust_a4"]["id"]),
        attempt_order=6,
        channel_used=Channel.SMS.value,
        delivery_status="DELIVERED",
    )

    critical_rows, _ = read_records(
        notification_batch_id=ctx["batch_advance"]["id"],
        customer_id=ctx["cust_a2"]["id"],
    )
    assert_record(
        record_for(critical_rows, ctx["cust_a2"]["id"]),
        attempt_order=1,
        channel_used=Channel.VOICE.value,
        delivery_status="DELIVERED",
    )
    assert_impact_counts(
        read_event(ctx["event_id"]), impacted=6, medical_baseline=1, critical_facility=1
    )
    assert_batch_outcome(
        ctx["batch_advance"],
        "FAILED_PARTIAL",
        target_count=6,
        delivered_count=5,
        unreachable_count=1,
    )


def test_the_time_critical_stages_narrow_the_language_set():
    """The Chinese-speaking household is written to in Chinese at 48 hours and in English at
    one hour, while the Spanish-speaking household keeps its language in both.

    "The two time-critical stages, `IMMINENT_1H` and `ACTIVATION`, are rendered only in
    `EN` and `ES`; the other three stages support the full set `EN`, `ES`, `ZH`, `TL`, and
    `VI`."

    "`language_used` is the account's `preferred_language` when that language is available
    for the stage, and falls back to `EN` otherwise — so a `VI`-speaking household receives
    its 48-hour advance warning in Vietnamese but its one-hour imminent warning in English."

    Design: Corner/calculations/notification_routing_narrows_the_language_set_on_time_critical_stages
    """
    ctx = build_imminent_dispatched_event()

    advance_rows, _ = read_records(
        notification_batch_id=ctx["batch_advance"]["id"],
        customer_id=ctx["cust_a3"]["id"],
    )
    assert_record(
        record_for(advance_rows, ctx["cust_a3"]["id"]),
        language_used=Language.ZH.value,
        channel_used=None,
        delivery_status="UNREACHABLE",
    )

    imminent_rows, _ = read_records(
        notification_batch_id=ctx["batch_imminent"]["id"],
        customer_id=ctx["cust_a3"]["id"],
    )
    assert_record(
        record_for(imminent_rows, ctx["cust_a3"]["id"]),
        language_used=Language.EN.value,
        channel_used=None,
        delivery_status="UNREACHABLE",
    )

    spanish_rows, _ = read_records(
        notification_batch_id=ctx["batch_imminent"]["id"],
        customer_id=ctx["cust_a1"]["id"],
    )
    assert_record(
        record_for(spanish_rows, ctx["cust_a1"]["id"]),
        language_used=Language.ES.value,
        channel_used=Channel.SMS.value,
        delivery_status="DELIVERED",
    )


def test_accessibility_needs_subtract_channels_before_the_waterfall_runs():
    """A large-print household keeps its SMS and is stamped for print, a teletype household
    loses VOICE and is reached by email, and the household whose needs forbid its only
    consented channel comes out unreachable.

    "Accessibility needs remove channels before the waterfall runs: a `TTY` need forbids
    `VOICE`, and an `AUDIO` need forbids both `SMS` and `EMAIL`."

    "Independently, `accessibility_format` is `LARGE_PRINT` when the account's
    `accessibility_needs` include `LARGE_PRINT`, and `STANDARD` otherwise."

    Design: Corner/calculations/notification_routing_honours_accessibility_forbidden_channels_and_large_print
    """
    ctx = build_feeder_chain()
    ctx["cust_a5"] = register_customer(
        ctx["alpha"]["id"],
        account_number="ACC-A5",
        notification_channels=[Channel.SMS.value],
        accessibility_needs=[AccessibilityNeed.LARGE_PRINT.value],
        address_zone_code="Z1",
    )
    ctx["cust_a6"] = register_customer(
        ctx["alpha"]["id"],
        account_number="ACC-A6",
        notification_channels=[Channel.VOICE.value, Channel.EMAIL.value],
        accessibility_needs=[AccessibilityNeed.TTY.value],
        address_zone_code="Z1",
    )
    ctx = build_advance_dispatched_event(ctx)
    batch_id = ctx["batch_advance"]["id"]

    large_print_rows, _ = read_records(
        notification_batch_id=batch_id, customer_id=ctx["cust_a5"]["id"]
    )
    assert_record(
        record_for(large_print_rows, ctx["cust_a5"]["id"]),
        channel_used=Channel.SMS.value,
        delivery_status="DELIVERED",
        accessibility_format="LARGE_PRINT",
    )

    teletype_rows, _ = read_records(
        notification_batch_id=batch_id, customer_id=ctx["cust_a6"]["id"]
    )
    assert_record(
        record_for(teletype_rows, ctx["cust_a6"]["id"]),
        channel_used=Channel.EMAIL.value,
        delivery_status="DELIVERED",
        accessibility_format="STANDARD",
    )

    unreachable, meta = read_records(
        notification_batch_id=batch_id, delivery_status="UNREACHABLE"
    )
    assert_integer(meta["total_count"], 1)
    assert unreachable[0]["customer_id"] == ctx["cust_a3"]["id"]
    assert unreachable[0]["channel_used"] is None
    assert_batch_outcome(
        read_batch(batch_id),
        "FAILED_PARTIAL",
        target_count=7,
        delivered_count=6,
        unreachable_count=1,
    )


# --------------------------------------------------------------------------
# The resource-center selector
# --------------------------------------------------------------------------
def test_the_selector_fills_from_the_certified_sites_not_the_largest_one():
    """Five seats are required and the two certified three-seat sites are taken in the order
    they were registered, leaving the hundred-seat uncertified site on standby.

    "Candidates are ranked by three keys in order: `accessibility_certified` descending, so
    certified sites come before uncertified ones; then `site_capacity` descending, so the
    largest site of equal certification comes first; then `created_at` ascending as the
    final tie-break — the site identifier is never used to rank."

    "Otherwise the server walks the ranking, stopping as soon as the capacity accumulated
    so far has reached or exceeded the required capacity, and activates each site it passes
    with an `activation_order` equal to its 1-based position among the sites activated by
    this call."

    Design: Corner/calculations/resource_center_selector_ranks_by_accessibility_then_capacity_then_created_at
    """
    mike, index, event = _armed_mike_event()
    uncertified = register_center(
        resource_center_code="CRC-W1",
        district_code="D-WEST",
        site_capacity=100,
        accessibility_certified=False,
    )
    first_certified = register_center(
        resource_center_code="CRC-W2",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=True,
    )
    second_certified = register_center(
        resource_center_code="CRC-W3",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=True,
    )

    summary = activate_centers(event["id"])

    assert_activation_summary(
        summary,
        activated_count=2,
        activated_capacity=6,
        unmet_capacity=0,
        activated_ids=[first_certified["id"], second_certified["id"]],
    )
    assert_center_state(
        read_center(first_certified["id"]),
        "ACTIVATED",
        activation_order=1,
        psps_event_id=event["id"],
        last_served_all_clear_at=MIKE_ALL_CLEAR_AT,
    )
    assert_center_state(
        read_center(second_certified["id"]), "ACTIVATED", activation_order=2
    )
    left_on_standby = read_center(uncertified["id"])
    assert_center_state(left_on_standby, "STANDBY", psps_event_id=None)
    assert left_on_standby["activation_order"] is None

    served = read_event(event["id"])
    assert_integer(served["crc_capacity_required"], 5)
    assert_integer(served["crc_capacity_served"], 6)
    assert_net_benefit(
        served,
        customer_impact_score=24.80,
        crc_mitigation_credit=1.24,
        adjusted_customer_impact_score=23.56,
        net_benefit_ratio=0.2801,
    )
    _, meta = validate_paginated(
        api_client.list_event_resource_centers(
            event["id"], OFFICER_HEADERS, params={"status": "ACTIVATED"}
        )
    )
    assert_integer(meta["total_count"], 2)


def test_a_short_pool_still_activates_and_reports_the_remainder():
    """Three seats against five required is a successful activation with the shortfall
    reported, and the partial coverage scales the credit down instead of being rounded away.

    "Either mode returns a summary object with four fields: `activated_count`, the number
    of sites activated by this call; `activated_capacity`, the sum of `site_capacity` over
    those sites; `unmet_capacity`, the required capacity less the event's post-activation
    `crc_capacity_served`, floored at zero so it never goes negative; and
    `activated_resource_center_ids`, the identifiers of the sites activated."

    "The coverage ratio is `crc_capacity_served` divided by `crc_capacity_required`, where
    a required capacity of zero is treated as one to keep the division defined, and the
    quotient is capped at 1 so over-provisioning earns no extra credit."

    "`crc_mitigation_credit` is `customer_impact_score` multiplied by the step-two rate and
    then by the step-three coverage ratio, rounded half up to two decimal places."

    Design: Corner/calculations/resource_center_selector_reports_unmet_capacity_when_the_pool_is_short
    """
    mike, index, event = _armed_mike_event()
    only_site = register_center(
        resource_center_code="CRC-W4",
        district_code="D-WEST",
        site_capacity=3,
        accessibility_certified=False,
    )

    summary = activate_centers(event["id"])

    assert_activation_summary(
        summary,
        activated_count=1,
        activated_capacity=3,
        unmet_capacity=2,
        activated_ids=[only_site["id"]],
    )
    assert_center_state(read_center(only_site["id"]), "ACTIVATED", activation_order=1)
    served = read_event(event["id"])
    assert_integer(served["crc_capacity_served"], 3)
    assert_net_benefit(
        served,
        customer_impact_score=24.80,
        crc_mitigation_credit=0.74,
        adjusted_customer_impact_score=24.06,
        ignition_risk_avoided_score=6.60,
        net_benefit_ratio=0.2743,
    )


# --------------------------------------------------------------------------
# Mitigation booking arithmetic
# --------------------------------------------------------------------------
def test_the_programme_factor_meets_the_terrain_multiplier_and_the_budget_truncates():
    """The same mileage scores differently on every terrain and under every programme, and
    the money is cut off at the whole cent rather than rounded up to it.

    "`budget_cents` is `planned_miles` multiplied by `unit_cost_per_mile_cents`,
    **truncated** to a whole cent rather than rounded."

    "The effectiveness factors are 0.62 for `COVERED_CONDUCTOR`, 1.00 for
    `UNDERGROUNDING`, 0.45 for `FAST_TRIP_SETTING`, and 0.18 for `INSPECTION_CYCLE`; the
    terrain multipliers, read from the circuit's `hftd_tier` live at the moment of
    computation, are 1.5 for `TIER_3`, 1.2 for `TIER_2`, 1.0 for `TIER_1`, and 0.5 for
    `NON_HFTD`."

    Design: Corner/calculations/mitigation_risk_reduction_score_and_truncated_budget_cents
    """
    tier_3 = register_circuit(
        circuit_code="ALPHA", hftd_tier=HftdTier.TIER_3.value, overhead_miles=7.0
    )
    tier_2 = register_circuit(
        circuit_code="BRAVO", hftd_tier=HftdTier.TIER_2.value, overhead_miles=6.0
    )
    tier_1 = register_circuit(
        circuit_code="INSPECT-1", hftd_tier=HftdTier.TIER_1.value, overhead_miles=5.0
    )
    non_hftd = _delta_circuit()

    inspection = book_project(
        tier_1["id"],
        project_code="MP-IC",
        program_type=ProgramType.INSPECTION_CYCLE.value,
        planned_miles=2.5,
        unit_cost_per_mile_cents=333,
    )
    underground = book_project(
        non_hftd["id"],
        project_code="MP-UG",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=9000000,
    )
    fast_trip = book_project(
        tier_2["id"],
        project_code="MP-FT",
        program_type=ProgramType.FAST_TRIP_SETTING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=180000,
    )
    covered = book_project(
        tier_3["id"],
        project_code="MP-CC2",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=2.0,
        unit_cost_per_mile_cents=1250000,
    )

    expected = (
        (inspection, 0.45, 832),
        (underground, 1.50, 27000000),
        (fast_trip, 1.62, 540000),
        (covered, 1.86, 2500000),
    )
    for project, score, budget in expected:
        assert_2dp(project["risk_reduction_score"], score)
        assert_integer(project["budget_cents"], budget)
        assert project["status"] == "DRAFT"
        assert_1dp(project["completed_miles"], 0.0)


# --------------------------------------------------------------------------
# Plan-filing roll-up
# --------------------------------------------------------------------------
def test_the_filing_aggregates_five_figures_out_of_the_finished_record():
    """The filing reads two completed packages, one closed outage, one 48-hour batch and a
    per-circuit customer-minute accumulation that no event-level duration could produce.

    "`customer_minutes_interrupted` accumulates over those events, taken in
    `actual_de_energized_at` ascending order with ties broken by event `created_at`
    ascending, and within each event over its `CONFIRMED` scope rows in scope-row
    `created_at` ascending order: for each such row, the number of whole minutes from the
    event's `actual_de_energized_at` to the row's `restored_at`, floored, is multiplied by
    that row's `customer_count_snapshot`, and the products are summed as integers."

    "`avg_notification_lead_minutes` looks only at the 48-hour advance batches of those
    closed events — batches whose `stage` is `ADVANCE_48H` and whose `status` is
    `DISPATCHED` or `FAILED_PARTIAL` — and is the sum of their `lead_time_minutes` divided
    by how many there are, rounded half up to two decimal places; when there are none, it
    is 0.00."

    Design: Corner/calculations/plan_filing_metrics_aggregate_closed_events_and_qualifying_projects
    """
    ctx = build_feeder_chain()
    delta = _delta_circuit()
    covered = build_approved_project(
        ctx["alpha"]["id"],
        project_code="MP-CC",
        program_type=ProgramType.COVERED_CONDUCTOR.value,
        planned_miles=4.0,
        unit_cost_per_mile_cents=1250000,
    )
    underground = build_approved_project(
        delta["id"],
        project_code="MP-UG3",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=3.0,
        unit_cost_per_mile_cents=9000000,
    )
    ctx = build_closed_event(ctx)
    assert_event_dimensions(ctx["event"], scope_status="CLOSED")
    record_completion(
        covered["id"],
        4.0,
        SECOND_COMPLETION_DATE,
        read_circuit(ctx["alpha"]["id"])["version"],
    )
    record_completion(
        underground["id"],
        3.0,
        SECOND_COMPLETION_DATE,
        read_circuit(delta["id"])["version"],
    )

    filing = open_filing(filing_code="WMP-2026", plan_year=2026)

    assert_filing_metrics(
        filing,
        qualifying_project_count=2,
        covered_conductor_miles_reported=4.0,
        underground_miles_reported=3.0,
        psps_event_count=1,
        customer_minutes_interrupted=9510,
        avg_notification_lead_minutes=2880.00,
        compliance_score=38.40,
    )

    submitted = submit_filing(filing["id"])

    assert_filing_tracks(submitted, status="SUBMITTED")
    assert_filing_metrics(
        submitted,
        qualifying_project_count=2,
        covered_conductor_miles_reported=4.0,
        underground_miles_reported=3.0,
        psps_event_count=1,
        customer_minutes_interrupted=9510,
        avg_notification_lead_minutes=2880.00,
        compliance_score=38.40,
    )
    assert read_project(covered["id"])["status"] == "COMPLETED"


def test_each_compliance_ratio_is_capped_before_its_weight_is_applied():
    """Twenty-five underground miles against a twenty-mile target earn the full forty points
    and not a point more, so the two axes that scored nothing stay at nothing.

    "It is a weighted attainment score out of 100 built from three ratios, each capped at 1
    before weighting: `underground_miles_reported` against a 20.0-mile annual target carries
    40 points, `covered_conductor_miles_reported` against a 50.0-mile annual target carries
    30 points, and `avg_notification_lead_minutes` against a 48-hour target — 2,880 minutes
    — carries the remaining 30 points."

    "The three weighted contributions are added, the sum is clamped to the range 0 through
    100, and exactly one rounding half up to two decimal places is applied after both the
    per-ratio caps and the final clamp."

    Design: Corner/calculations/plan_filing_compliance_score_clamps_each_ratio_before_weighting
    """
    delta = _delta_circuit()
    project = build_approved_project(
        delta["id"],
        project_code="UG-CLAMP",
        program_type=ProgramType.UNDERGROUNDING.value,
        planned_miles=25.0,
        unit_cost_per_mile_cents=9000000,
    )
    project = record_completion(
        project["id"], 25.0, FIRST_COMPLETION_DATE, read_circuit(delta["id"])["version"]
    )
    assert project["status"] == "COMPLETED"

    filing = open_filing(filing_code="WMP-CLAMP", plan_year=2026)

    assert_filing_metrics(
        filing,
        qualifying_project_count=1,
        underground_miles_reported=25.0,
        covered_conductor_miles_reported=0.0,
        psps_event_count=0,
        customer_minutes_interrupted=0,
        avg_notification_lead_minutes=0.00,
        compliance_score=40.00,
    )
    assert_hardening_ledger(
        read_circuit(delta["id"]),
        covered_conductor_miles=0.0,
        underground_miles=25.0,
        hardened_fraction=1.0000,
    )


# --------------------------------------------------------------------------
# Lead time
# --------------------------------------------------------------------------
def test_the_lead_time_floors_the_half_minute_in_both_directions():
    """Two batches scheduled for the same instant are measured against the clock at dispatch
    and diverge across the sixty-minute floor by a single minute of arithmetic.

    "The `scheduled_send_at` the operator wrote down is a plan, not the measurement:
    `dispatched_at` is stamped from the logical clock at the moment dispatch runs, and
    `lead_time_minutes` is computed as the number of whole minutes from `dispatched_at` to
    the event's `forecast_onset_at`, floored toward negative infinity — so a dispatch that
    happens after the onset yields a negative lead time."

    "A lead time strictly below the stage minimum is refused with
    `ERR_NOTIFICATION_LEAD_TIME_SHORT`; a lead time exactly equal to the minimum is
    accepted."

    Design: Corner/calculations/notification_lead_time_floors_the_minute_difference
    """
    ctx = build_armed_event()
    first = plan_batch(
        ctx["event_id"], NotificationStage.IMMINENT_1H.value, IMMINENT_SCHEDULED_AT
    )
    second = plan_batch(
        ctx["event_id"], NotificationStage.IMMINENT_1H.value, IMMINENT_SCHEDULED_AT
    )
    move_clock(JUST_OVER_THE_HOUR)

    dispatched = dispatch_batch(first["id"])

    assert_integer(dispatched["lead_time_minutes"], 60)
    assert dispatched["dispatched_at"].startswith("2026-08-15T16:59:30")
    assert_event_dimensions(
        read_event(ctx["event_id"]), notification_status="IMMINENT_SENT"
    )

    move_clock(JUST_UNDER_THE_HOUR)
    response = api_client.dispatch_notification_batch(second["id"], LIAISON_HEADERS)

    validate_error(response, ERR_NOTIFICATION_LEAD_TIME_SHORT, 422)
    refused = read_batch(second["id"])
    assert refused["status"] == "PENDING"
    assert refused["dispatched_at"] is None
    assert refused["lead_time_minutes"] is None
    assert first["scheduled_send_at"] == second["scheduled_send_at"]
    assert len(read_scope_rows(ctx["event_id"])) == 3
