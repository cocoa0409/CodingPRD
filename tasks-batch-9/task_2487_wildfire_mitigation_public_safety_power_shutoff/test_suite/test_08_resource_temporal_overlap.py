"""Two occupation rules with deliberately different interval semantics: a circuit's
half-open damaging-weather window, and a resource center's closed previous-service window
extended by a four-hour reset buffer."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_CIRCUIT_WINDOW_CONFLICT,
    ERR_RESOURCE_CENTER_BUFFER_CONFLICT,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_center_state,
    assert_circuit_state,
    assert_event_dimensions,
    assert_fpi,
    assert_instant,
    assert_integer,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.fixtures import (
    activate_centers,
    arm_event,
    build_scoped_event,
    close_event,
    complete_patrol,
    compute_index,
    de_energize_event,
    declare_all_clear,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    plan_batch,
    re_energize,
    read_center,
    read_circuit,
    read_event,
    read_scope_rows,
    register_center,
    register_circuit,
    register_customer,
    register_station,
    schedule_patrol,
    scope_event,
    start_patrol,
)
from test_helpers.test_users import OFFICER_HEADERS
from test_helpers.types import (
    ComputationVariant,
    CustomerClass,
    HftdTier,
    NotificationStage,
    TelemetryStatus,
)

SECOND_FORECAST_DATE = "2026-08-16"
PRIOR_FORECAST_DATE = "2026-08-14"
PRIOR_ONSET_AT = "2026-08-14T18:00:00Z"
PRIOR_ALL_CLEAR_AT = "2026-08-15T18:00:00Z"
TOUCHING_ONSET_AT = "2026-08-16T18:00:00Z"
TOUCHING_ALL_CLEAR_AT = "2026-08-17T18:00:00Z"
OVERLAPPING_ONSET_AT = "2026-08-16T17:00:00Z"
OVERLAPPING_ALL_CLEAR_AT = "2026-08-17T17:00:00Z"

HOTEL_FORECAST_DATE = "2026-08-20"
HOTEL_ONSET_AT = "2026-08-20T06:00:00Z"
HOTEL_ALL_CLEAR_AT = "2026-08-20T18:00:00Z"
HOTEL_ADVANCE_SEND_AT = "2026-08-18T06:00:00Z"
HOTEL_IMMINENT_SEND_AT = "2026-08-20T05:00:00Z"
HOTEL_DE_ENERGIZED_AT = "2026-08-20T07:00:00Z"
HOTEL_PATROL_START_AT = "2026-08-20T17:00:00Z"
HOTEL_PATROL_DONE_AT = "2026-08-20T19:00:00Z"
HOTEL_RESTORED_AT = "2026-08-20T20:00:00Z"
INSIDE_BUFFER_ONSET_AT = "2026-08-20T21:59:00Z"
INSIDE_BUFFER_ALL_CLEAR_AT = "2026-08-21T09:59:00Z"
ON_BUFFER_EDGE_ONSET_AT = "2026-08-20T22:00:00Z"
ON_BUFFER_EDGE_ALL_CLEAR_AT = "2026-08-21T10:00:00Z"


def _chain_with_a_second_days_forecast():
    """EV-1 holds all three circuits over 2026-08-15T18:00Z to 2026-08-16T18:00Z, and the
    chain also carries a 2026-08-16 forecast for the following day's events."""
    ctx = build_scoped_event()
    ctx["fpi_second_day"] = compute_index(
        ctx["alpha"]["id"], SECOND_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    return ctx


def _hotel_with_a_demobilized_resource_center():
    """CRC-S1 has served EV-H through a complete shutoff cycle, so it is DEMOBILIZED with
    its last service all-clear recorded at 2026-08-20T18:00Z and HOTEL is energized."""
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
    center = register_center(
        resource_center_code="CRC-S1",
        district_code="D-SOUTH",
        site_capacity=150,
        accessibility_certified=True,
    )
    served = open_event(
        index["id"],
        onset_at=HOTEL_ONSET_AT,
        all_clear_at=HOTEL_ALL_CLEAR_AT,
        event_code="EV-H",
    )
    scope_event(served["id"], served["version"])
    activate_centers(served["id"], [center["id"]])

    advance = plan_batch(
        served["id"], NotificationStage.ADVANCE_48H.value, HOTEL_ADVANCE_SEND_AT
    )
    move_clock(HOTEL_ADVANCE_SEND_AT)
    dispatch_batch(advance["id"])
    arm_event(served["id"])
    imminent = plan_batch(
        served["id"], NotificationStage.IMMINENT_1H.value, HOTEL_IMMINENT_SEND_AT
    )
    move_clock(HOTEL_IMMINENT_SEND_AT)
    dispatch_batch(imminent["id"])
    move_clock(HOTEL_DE_ENERGIZED_AT)
    de_energize_event(served["id"])
    declare_all_clear(served["id"])
    patrol = schedule_patrol(
        served["id"],
        hotel["id"],
        HOTEL_PATROL_START_AT,
        HOTEL_PATROL_DONE_AT,
        patrol_lead_user_id="crew_lead_h",
    )
    move_clock(HOTEL_PATROL_START_AT)
    start_patrol(patrol["id"])
    move_clock(HOTEL_PATROL_DONE_AT)
    complete_patrol(patrol["id"], 8.0)
    move_clock(HOTEL_RESTORED_AT)
    re_energize(hotel["id"])
    close_event(served["id"])
    return hotel, index, served, center


def _later_event_over_hotel(index_id, onset_at, all_clear_at, event_code):
    """A second SCOPED event over the re-energized HOTEL, opened on the same forecast."""
    event = open_event(
        index_id, onset_at=onset_at, all_clear_at=all_clear_at, event_code=event_code
    )
    return scope_event(event["id"], event["version"])


# --------------------------------------------------------------------------
# Circuit occupation: half-open windows
# --------------------------------------------------------------------------
def test_an_hour_of_overlap_refuses_the_whole_scope_determination():
    """EV-OVERLAP opens one hour before EV-1's all-clear and is turned away with no scope
    rows written at all.

    "Any conflict refuses the whole call with `ERR_CIRCUIT_WINDOW_CONFLICT` and leaves no
    scope rows behind."

    Design: Difficulty/resource_temporal_overlap/circuit_event_windows_half_open_adjacency_allowed
    """
    ctx = _chain_with_a_second_days_forecast()
    overlapping = open_event(
        ctx["fpi_second_day"]["id"],
        onset_at=OVERLAPPING_ONSET_AT,
        all_clear_at=OVERLAPPING_ALL_CLEAR_AT,
        event_code="EV-OVERLAP",
    )

    response = api_client.scope_psps_event(
        overlapping["id"],
        factories.scope_payload(overlapping["version"]),
        OFFICER_HEADERS,
    )

    validate_error(response, ERR_CIRCUIT_WINDOW_CONFLICT, 409)
    refused = read_event(overlapping["id"])
    assert_event_dimensions(refused, scope_status="DRAFT")
    assert_scope_counts(refused, confirmed=0, excluded=0)
    _, meta = validate_paginated(
        api_client.list_event_scopes(overlapping["id"], OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 0)
    assert_scope_counts(read_event(ctx["event_id"]), confirmed=3, excluded=0)


def test_an_onset_exactly_on_the_previous_all_clear_is_not_a_conflict():
    """EV-TOUCH opens at the very instant EV-1's window ends and takes all three circuits,
    scoring them on the lower second-day forecast.

    "Touching windows, where one event's all-clear falls exactly on the other's onset, do
    not conflict."

    Design: Difficulty/resource_temporal_overlap/circuit_event_windows_half_open_adjacency_allowed
    """
    ctx = _chain_with_a_second_days_forecast()
    assert_fpi(ctx["fpi_second_day"], 78.66, "R5")

    touching = open_event(
        ctx["fpi_second_day"]["id"],
        onset_at=TOUCHING_ONSET_AT,
        all_clear_at=TOUCHING_ALL_CLEAR_AT,
        event_code="EV-TOUCH",
    )
    scoped = scope_event(touching["id"], touching["version"])

    assert_event_dimensions(scoped, scope_status="SCOPED")
    assert_scope_counts(scoped, confirmed=3, excluded=0)
    assert_2dp(scoped["ignition_risk_avoided_score"], 14.16)

    rows = read_scope_rows(touching["id"])
    assert_scope_row(rows, ctx["alpha"]["id"], ignition_risk_term=5.51)
    assert_scope_row(rows, ctx["bravo"]["id"], ignition_risk_term=4.72)
    assert_scope_row(rows, ctx["charlie"]["id"], ignition_risk_term=3.93)

    untouched = read_scope_rows(ctx["event_id"])
    assert_scope_row(untouched, ctx["alpha"]["id"], fpi_score_applied=85.93)
    assert_scope_counts(read_event(ctx["event_id"]), confirmed=3, excluded=0)


def test_the_guard_reads_the_whole_candidate_set_and_lets_a_preceding_window_through():
    """EV-PRIOR ends at the very instant EV-1 begins, so the guard clears all three
    candidates and both events hold the same chain side by side.

    "A candidate conflicts when some other event already holds it in a `CONFIRMED` scope
    row, that other event's `scope_status` is `SCOPED`, `ARMED`, `ACTIVE`, or `RESTORING`,
    and the two events' damaging-weather windows overlap — meaning the other event's onset
    is strictly earlier than this event's all-clear **and** this event's onset is strictly
    earlier than the other event's all-clear."

    Design: Difficulty/resource_temporal_overlap/circuit_event_windows_half_open_adjacency_allowed
    """
    ctx = build_scoped_event()
    prior_index = compute_index(
        ctx["alpha"]["id"], PRIOR_FORECAST_DATE, ComputationVariant.FORECAST.value
    )
    preceding = open_event(
        prior_index["id"],
        onset_at=PRIOR_ONSET_AT,
        all_clear_at=PRIOR_ALL_CLEAR_AT,
        event_code="EV-PRIOR",
    )

    scoped = scope_event(preceding["id"], preceding["version"])

    assert_event_dimensions(scoped, scope_status="SCOPED")
    assert_scope_counts(scoped, confirmed=3, excluded=0)
    rows = read_scope_rows(preceding["id"])
    for key in ("alpha", "bravo", "charlie"):
        assert_scope_row(rows, ctx[key]["id"], scope_status="CONFIRMED")
    assert_scope_counts(read_event(ctx["event_id"]), confirmed=3, excluded=0)
    _, meta = validate_paginated(
        api_client.list_circuit_event_scopes(ctx["alpha"]["id"], OFFICER_HEADERS)
    )
    assert_integer(meta["total_count"], 2)


# --------------------------------------------------------------------------
# Resource-center occupation: the closed 240-minute reset buffer
# --------------------------------------------------------------------------
def test_an_onset_one_minute_inside_the_reset_buffer_is_refused():
    """239 minutes after CRC-S1's last all-clear is still inside the four-hour buffer, so
    naming the site refuses the whole activation.

    "It also establishes what a **reset-buffer collision** means: a site collides when its
    `last_served_all_clear_at` is non-null and the new event's `forecast_onset_at` falls
    strictly earlier than that instant advanced by a 240-minute — four-hour — reset
    buffer."

    Design: Difficulty/resource_temporal_overlap/resource_center_reset_buffer_closed_interval_plus_240_minutes
    """
    hotel, index, served, center = _hotel_with_a_demobilized_resource_center()
    assert_center_state(
        read_center(center["id"]),
        "DEMOBILIZED",
        psps_event_id=served["id"],
        last_served_all_clear_at=HOTEL_ALL_CLEAR_AT,
    )
    too_early = _later_event_over_hotel(
        index["id"],
        INSIDE_BUFFER_ONSET_AT,
        INSIDE_BUFFER_ALL_CLEAR_AT,
        "EV-EARLY",
    )

    response = api_client.activate_resource_centers(
        too_early["id"],
        factories.activation_payload([center["id"]]),
        OFFICER_HEADERS,
    )

    validate_error(response, ERR_RESOURCE_CENTER_BUFFER_CONFLICT, 409)
    unchanged = read_center(center["id"])
    assert_center_state(
        unchanged,
        "DEMOBILIZED",
        psps_event_id=served["id"],
        last_served_all_clear_at=HOTEL_ALL_CLEAR_AT,
    )
    refused_event = read_event(too_early["id"])
    assert_integer(refused_event["crc_capacity_served"], 0)
    assert_2dp(refused_event["crc_mitigation_credit"], 0.00)


def test_an_onset_exactly_on_the_buffer_edge_reopens_the_site():
    """240 minutes after the last all-clear the same site is available again, comes back
    out of DEMOBILIZED, and takes the new event's all-clear as its service mark.

    "An onset falling exactly on the buffer edge is accepted; the buffer is closed at its
    trailing end."

    "Each activated site records the `psps_event_id` it is serving, stamps `activated_at`
    from the logical clock, records its `activation_order`, and sets
    `last_served_all_clear_at` to the event's `forecast_all_clear_at`."

    Design: Difficulty/resource_temporal_overlap/resource_center_reset_buffer_closed_interval_plus_240_minutes
    """
    hotel, index, served, center = _hotel_with_a_demobilized_resource_center()
    assert_circuit_state(read_circuit(hotel["id"]), energization_state="ENERGIZED")
    on_the_edge = _later_event_over_hotel(
        index["id"],
        ON_BUFFER_EDGE_ONSET_AT,
        ON_BUFFER_EDGE_ALL_CLEAR_AT,
        "EV-EDGE",
    )

    activate_centers(on_the_edge["id"], [center["id"]])

    reopened = read_center(center["id"])
    assert_center_state(
        reopened,
        "ACTIVATED",
        activation_order=1,
        psps_event_id=on_the_edge["id"],
        last_served_all_clear_at=ON_BUFFER_EDGE_ALL_CLEAR_AT,
    )
    assert_instant(reopened["activated_at"], HOTEL_RESTORED_AT)
    assert_integer(read_event(on_the_edge["id"])["crc_capacity_served"], 150)


def test_demobilization_keeps_the_service_mark_the_buffer_is_measured_from():
    """The site stands down at 20:00Z but the buffer is still measured from the event's
    18:00Z all-clear, which is why an onset at 21:59Z is inside it.

    "Its `last_served_all_clear_at` is deliberately left in place so the reset buffer
    still applies to the next event."

    Design: Difficulty/resource_temporal_overlap/resource_center_reset_buffer_closed_interval_plus_240_minutes
    """
    hotel, index, served, center = _hotel_with_a_demobilized_resource_center()

    stood_down = read_center(center["id"])
    assert_center_state(
        stood_down,
        "DEMOBILIZED",
        psps_event_id=served["id"],
        last_served_all_clear_at=HOTEL_ALL_CLEAR_AT,
    )
    assert_instant(stood_down["demobilized_at"], HOTEL_RESTORED_AT)
    assert_instant(stood_down["last_served_all_clear_at"], HOTEL_ALL_CLEAR_AT)
    assert read_event(served["id"])["scope_status"] == "CLOSED"
