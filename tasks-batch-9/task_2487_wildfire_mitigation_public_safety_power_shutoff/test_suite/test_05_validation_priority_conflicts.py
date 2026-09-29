"""Requests that break two rules at once, where the normative priority order decides
which error the caller actually receives."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_ADVANCE_NOTIFICATION_MISSING,
    ERR_CRITICAL_NOTIFICATION_INCOMPLETE,
    ERR_EVENT_NOT_ARMED,
    ERR_NET_BENEFIT_BELOW_THRESHOLD,
    ERR_NO_CIRCUITS_IN_SCOPE,
    ERR_NOTIFICATION_WINDOW_INVALID,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_circuit_state,
    assert_event_dimensions,
    assert_fpi,
    assert_integer,
    assert_net_benefit,
    assert_scope_counts,
    assert_scope_row,
)
from test_helpers.constants import FAST_TRIP_EXEMPTION_JUSTIFICATION
from test_helpers.fixtures import (
    build_armed_event,
    build_scoped_event,
    compute_index,
    dispatch_batch,
    file_observation,
    move_clock,
    open_event,
    plan_batch,
    read_circuit,
    read_event,
    read_scope_rows,
    register_circuit,
    register_customer,
    register_station,
    scope_event,
)
from test_helpers.test_users import LIAISON_HEADERS, OFFICER_HEADERS
from test_helpers.types import (
    ComputationVariant,
    CustomerClass,
    HftdTier,
    NotificationStage,
    TelemetryStatus,
)

GOLF_ONSET_AT = "2026-08-25T00:00:00Z"
GOLF_ALL_CLEAR_AT = "2026-08-28T00:00:00Z"
GOLF_ADVANCE_SEND_AT = "2026-08-23T00:00:00Z"
FOXTROT_ONSET_AT = "2026-09-05T18:00:00Z"
FOXTROT_ALL_CLEAR_AT = "2026-09-06T18:00:00Z"
FOXTROT_EARLY_SEND_AT = "2026-09-04T18:00:00Z"


def _golf_scoped_event():
    """GOLF scores 69.60 / R4 over a 72-hour window, so its ratio of 0.0302 is far below
    the arming threshold — and no advance batch has been planned at all."""
    golf = register_circuit(
        circuit_code="GOLF",
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=5.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=False,
    )
    station = register_station(
        golf["id"],
        station_code="WS-G1",
        elevation_ft=2200,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        "2026-08-24T12:00:00Z",
        wind_gust_mph=52.0,
        relative_humidity_pct=30.0,
        temperature_f=97.0,
        dead_fuel_moisture_pct=9.0,
    )
    index = compute_index(golf["id"], "2026-08-25", ComputationVariant.FORECAST.value)
    register_customer(
        golf["id"],
        account_number="ACC-G1",
        customer_class=CustomerClass.CRITICAL_FACILITY.value,
        notification_channels=["VOICE"],
        address_zone_code="ZG",
    )
    register_customer(
        golf["id"],
        account_number="ACC-G2",
        medical_baseline=True,
        notification_channels=["SMS"],
        address_zone_code="ZG",
    )
    event = open_event(
        index["id"],
        onset_at=GOLF_ONSET_AT,
        all_clear_at=GOLF_ALL_CLEAR_AT,
        event_code="EV-G",
    )
    scoped = scope_event(event["id"], event["version"])
    return golf, index, scoped


def _foxtrot_exempted_event():
    """FOXTROT scores 74.91 — tier R4 exactly — with fast-trip settings armed, so its
    only scope row is written EXCLUDED and the event has nobody to notify."""
    foxtrot = register_circuit(
        circuit_code="FOXTROT",
        district_code="D-EAST",
        hftd_tier=HftdTier.TIER_2.value,
        overhead_miles=6.0,
        equipment_condition_index=80,
        inspection_cycle_months=36,
        last_inspection_completed_at="2026-05-01T00:00:00Z",
        fast_trip_enabled=True,
    )
    station = register_station(
        foxtrot["id"],
        station_code="WS-F1",
        elevation_ft=2400,
        representativeness_weight=1.00,
        telemetry_status=TelemetryStatus.ONLINE.value,
    )
    file_observation(
        station["id"],
        "2026-09-04T12:00:00Z",
        wind_gust_mph=51.9,
        relative_humidity_pct=10.0,
        temperature_f=103.0,
        dead_fuel_moisture_pct=6.0,
    )
    index = compute_index(foxtrot["id"], "2026-09-05", ComputationVariant.FORECAST.value)
    register_customer(
        foxtrot["id"],
        account_number="ACC-F1",
        notification_channels=["SMS"],
        address_zone_code="ZF",
    )
    event = open_event(
        index["id"],
        onset_at=FOXTROT_ONSET_AT,
        all_clear_at=FOXTROT_ALL_CLEAR_AT,
        event_code="EV-F",
    )
    scoped = scope_event(event["id"], event["version"])
    return foxtrot, index, scoped


# --------------------------------------------------------------------------
# Own state before notification safety, on de-energization
# --------------------------------------------------------------------------
def test_de_energizing_a_merely_scoped_event_reports_the_state_error():
    """A scoped event with no notification at all breaks both gates, and the caller is
    told the event is not armed.

    "De-energization is admitted only while the event's `scope_status` is `ARMED`,
    otherwise `ERR_EVENT_NOT_ARMED`, and it carries the strictest gate in the system:
    there must be an `IMMINENT_1H` batch for the event whose `status` is `DISPATCHED` or
    `FAILED_PARTIAL`, **and** every account on a `CONFIRMED`-scoped circuit whose
    `notification_tier` is `TIER_A_CRITICAL` or `TIER_B_MEDICAL` must have a record in
    that batch whose `delivery_status` is `DELIVERED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_notification_safety_on_deenergize
    """
    ctx = build_scoped_event()

    response = api_client.de_energize_psps_event(ctx["event_id"], OFFICER_HEADERS)

    validate_error(response, ERR_EVENT_NOT_ARMED, 409)
    event = read_event(ctx["event_id"])
    assert_event_dimensions(
        event, scope_status="SCOPED", notification_status="NOT_STARTED"
    )
    assert event["actual_de_energized_at"] is None
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]), energization_state="ENERGIZED"
    )


def test_the_notification_gate_surfaces_only_once_the_event_is_armed():
    """Arming first clears the state guard, and the same call then reports the critical
    notification the earlier error had been hiding.

    "This ordering is normative: a caller who violates two rules receives the error of
    the earlier one, and a test that provokes a late-priority failure must not be masked
    by an early-priority one."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_notification_safety_on_deenergize
    """
    ctx = build_armed_event()

    response = api_client.de_energize_psps_event(ctx["event_id"], OFFICER_HEADERS)

    validate_error(response, ERR_CRITICAL_NOTIFICATION_INCOMPLETE, 422)
    event = read_event(ctx["event_id"])
    assert_event_dimensions(
        event, scope_status="ARMED", notification_status="ADVANCE_SENT"
    )
    assert event["actual_de_energized_at"] is None
    assert_circuit_state(
        read_circuit(ctx["alpha"]["id"]),
        energization_state="DE_ENERGIZATION_PENDING",
        risk_posture="LOCKED",
    )


# --------------------------------------------------------------------------
# Notification safety before the fiscal threshold, on arming
# --------------------------------------------------------------------------
def test_arming_without_an_advance_batch_reports_the_notification_gap():
    """GOLF's ratio is nowhere near the threshold, but the missing 48-hour warning is the
    earlier gate and is what the caller hears about.

    "There must be an `ADVANCE_48H` batch for the event whose `status` is `DISPATCHED` or
    `FAILED_PARTIAL`, or the request is refused with `ERR_ADVANCE_NOTIFICATION_MISSING` —
    a partial delivery failure does **not** block arming, because the 48-hour warning has
    demonstrably gone out."

    Design: Difficulty/priority_pair_validation_conflict/notification_safety_beats_fiscal_threshold_on_arm
    """
    golf, index, scoped = _golf_scoped_event()

    response = api_client.arm_psps_event(scoped["id"], OFFICER_HEADERS)

    validate_error(response, ERR_ADVANCE_NOTIFICATION_MISSING, 422)
    assert_fpi(index, 69.60, "R4")
    assert_event_dimensions(read_event(scoped["id"]), scope_status="SCOPED")
    assert_circuit_state(read_circuit(golf["id"]), energization_state="ENERGIZED")


def test_the_threshold_gate_surfaces_once_the_advance_warning_has_gone_out():
    """With the 48-hour batch delivered, the arming call reaches the fiscal gate and is
    refused on a ratio of 0.0302.

    "And the event's `net_benefit_ratio` must be at least 0.25, or the request is refused
    with `ERR_NET_BENEFIT_BELOW_THRESHOLD`; a ratio of exactly 0.2500 clears the gate."

    Design: Difficulty/priority_pair_validation_conflict/notification_safety_beats_fiscal_threshold_on_arm
    """
    golf, index, scoped = _golf_scoped_event()
    assert_net_benefit(
        scoped,
        variant="PRE_EVENT",
        duration_hours=72,
        customer_impact_score=115.20,
        ignition_risk_avoided_score=3.48,
        net_benefit_ratio=0.0302,
    )

    batch = plan_batch(
        scoped["id"], NotificationStage.ADVANCE_48H.value, GOLF_ADVANCE_SEND_AT
    )
    move_clock(GOLF_ADVANCE_SEND_AT)
    dispatched = dispatch_batch(batch["id"])
    assert dispatched["status"] == "DISPATCHED"

    response = api_client.arm_psps_event(scoped["id"], OFFICER_HEADERS)

    validate_error(response, ERR_NET_BENEFIT_BELOW_THRESHOLD, 422)
    assert_event_dimensions(
        read_event(scoped["id"]),
        scope_status="SCOPED",
        notification_status="ADVANCE_SENT",
    )
    assert_circuit_state(read_circuit(golf["id"]), energization_state="ENERGIZED")


# --------------------------------------------------------------------------
# The send window before the referential scope check, on batch planning
# --------------------------------------------------------------------------
def test_planning_a_batch_at_the_onset_reports_the_window_error():
    """FOXTROT's event has no confirmed circuit at all, yet a send instant sitting on the
    onset is rejected for its window and not for its empty scope.

    "Planning is refused with `ERR_NO_CIRCUITS_IN_SCOPE` when the event's
    `confirmed_scope_count` is zero — there is nobody to notify — and, for the three
    pre-onset stages `ADVANCE_48H`, `ADVANCE_24H`, and `IMMINENT_1H`, with
    `ERR_NOTIFICATION_WINDOW_INVALID` when `scheduled_send_at` falls at or after the
    event's `forecast_onset_at`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_beats_referential_scope_on_batch_create
    """
    foxtrot, index, scoped = _foxtrot_exempted_event()

    response = api_client.create_notification_batch(
        factories.notification_batch_payload(
            scoped["id"],
            FOXTROT_ONSET_AT,
            stage=NotificationStage.ADVANCE_48H.value,
        ),
        LIAISON_HEADERS,
    )

    validate_error(response, ERR_NOTIFICATION_WINDOW_INVALID, 422)
    assert_fpi(index, 74.91, "R4")
    assert_scope_counts(read_event(scoped["id"]), confirmed=0, excluded=1)
    _, meta = validate_paginated(
        api_client.list_event_notification_batches(scoped["id"], LIAISON_HEADERS)
    )
    assert_integer(meta["total_count"], 0)


def test_the_empty_scope_error_surfaces_once_the_send_instant_is_well_formed():
    """The fast-trip exemption is what emptied the confirmed set, so a send instant
    comfortably before the onset finally reports that there is nobody to notify.

    "A primary candidate whose `fast_trip_enabled` is true **and** whose qualifying index
    sits at tier `R4` exactly is written as a scope row with `inclusion_basis` of
    `PRIMARY_RISK` but `scope_status` of `EXCLUDED`, with `exclusion_justification` set to
    the literal string `FAST_TRIP_MITIGATED_R4`, with `fpi_score_applied` carrying the
    index's `fpi_score`, and with `ignition_risk_term` pinned at 0.00 — and its downstream
    subtree is **not** walked, so an exempted circuit shields its dependants from the
    shutoff too."

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_beats_referential_scope_on_batch_create
    """
    foxtrot, index, scoped = _foxtrot_exempted_event()

    rows = read_scope_rows(scoped["id"])
    assert_scope_row(
        rows,
        foxtrot["id"],
        scope_status="EXCLUDED",
        inclusion_basis="PRIMARY_RISK",
        fpi_score_applied=74.91,
        ignition_risk_term=0.00,
        exclusion_justification=FAST_TRIP_EXEMPTION_JUSTIFICATION,
    )
    assert_2dp(scoped["ignition_risk_avoided_score"], 0.00)

    response = api_client.create_notification_batch(
        factories.notification_batch_payload(
            scoped["id"],
            FOXTROT_EARLY_SEND_AT,
            stage=NotificationStage.ADVANCE_48H.value,
        ),
        LIAISON_HEADERS,
    )

    validate_error(response, ERR_NO_CIRCUITS_IN_SCOPE, 422)
    _, meta = validate_paginated(
        api_client.list_event_notification_batches(scoped["id"], LIAISON_HEADERS)
    )
    assert_integer(meta["total_count"], 0)
