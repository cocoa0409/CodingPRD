"""Request-payload builders.

Each builder returns the minimal valid body for one endpoint and accepts keyword
overrides.  Passing ``None`` for an optional field omits it, which is how a test
exercises the contract's declared defaults; passing an explicit value sends it.
"""

import itertools

from .types import (
    Channel,
    ComputationVariant,
    CustomerClass,
    HftdTier,
    Language,
    NotificationStage,
    PatrolMode,
    ProgramType,
    TelemetryStatus,
)

_counter = itertools.count(1)


def unique_suffix():
    """A monotone suffix so natural keys stay unique inside one test."""
    return f"{next(_counter):04d}"


def _drop_none(payload):
    return {k: v for k, v in payload.items() if v is not None}


# --------------------------------------------------------------------------
# Circuits (PRD §3.1)
# --------------------------------------------------------------------------
def circuit_payload(
    circuit_code=None,
    district_code="D-NORTH",
    hftd_tier=HftdTier.TIER_3.value,
    overhead_miles=7.0,
    equipment_condition_index=55,
    inspection_cycle_months=36,
    last_inspection_completed_at="2026-05-01T00:00:00Z",
    fast_trip_enabled=False,
    upstream_circuit_id=None,
    **extra,
):
    payload = {
        "circuit_code": circuit_code or f"CKT-{unique_suffix()}",
        "district_code": district_code,
        "hftd_tier": hftd_tier,
        "overhead_miles": overhead_miles,
        "equipment_condition_index": equipment_condition_index,
        "inspection_cycle_months": inspection_cycle_months,
        "last_inspection_completed_at": last_inspection_completed_at,
        "fast_trip_enabled": fast_trip_enabled,
        "upstream_circuit_id": upstream_circuit_id,
    }
    payload = _drop_none(payload)
    payload.update(extra)
    return payload


def minimal_circuit_payload(circuit_code=None, **extra):
    """Only the required fields, so every declared default is exercised."""
    payload = {
        "circuit_code": circuit_code or f"CKT-{unique_suffix()}",
        "district_code": "D-NORTH",
        "hftd_tier": HftdTier.TIER_2.value,
        "overhead_miles": 5.0,
        "equipment_condition_index": 80,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Served accounts (PRD §3.1)
# --------------------------------------------------------------------------
def customer_payload(
    circuit_id,
    account_number=None,
    customer_class=CustomerClass.RESIDENTIAL.value,
    preferred_language=Language.EN.value,
    notification_channels=None,
    address_zone_code="Z1",
    medical_baseline=None,
    accessibility_needs=None,
    **extra,
):
    payload = {
        "account_number": account_number or f"ACC-{unique_suffix()}",
        "circuit_id": circuit_id,
        "customer_class": customer_class,
        "preferred_language": preferred_language,
        "notification_channels": (
            [Channel.SMS.value] if notification_channels is None else notification_channels
        ),
        "address_zone_code": address_zone_code,
        "medical_baseline": medical_baseline,
        "accessibility_needs": accessibility_needs,
    }
    payload = _drop_none(payload)
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# The weather desk (PRD §3.2)
# --------------------------------------------------------------------------
def weather_station_payload(
    circuit_id,
    station_code=None,
    elevation_ft=3200,
    representativeness_weight=1.00,
    telemetry_status=TelemetryStatus.ONLINE.value,
    **extra,
):
    payload = {
        "station_code": station_code or f"WS-{unique_suffix()}",
        "circuit_id": circuit_id,
        "elevation_ft": elevation_ft,
        "representativeness_weight": representativeness_weight,
        "telemetry_status": telemetry_status,
    }
    payload = _drop_none(payload)
    payload.update(extra)
    return payload


def observation_payload(
    weather_station_id,
    observed_at,
    wind_gust_mph=52.0,
    relative_humidity_pct=62.0,
    temperature_f=92.0,
    dead_fuel_moisture_pct=9.0,
    **extra,
):
    payload = {
        "weather_station_id": weather_station_id,
        "observed_at": observed_at,
        "wind_gust_mph": wind_gust_mph,
        "relative_humidity_pct": relative_humidity_pct,
        "temperature_f": temperature_f,
        "dead_fuel_moisture_pct": dead_fuel_moisture_pct,
    }
    payload.update(extra)
    return payload


def fpi_payload(
    circuit_id,
    forecast_date,
    computation_variant=ComputationVariant.FORECAST.value,
    **extra,
):
    payload = {
        "circuit_id": circuit_id,
        "forecast_date": forecast_date,
        "computation_variant": computation_variant,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Shutoff events (PRD §3.4)
# --------------------------------------------------------------------------
def psps_event_payload(
    trigger_fire_potential_index_id,
    forecast_onset_at,
    forecast_all_clear_at,
    event_code=None,
    **extra,
):
    payload = {
        "event_code": event_code or f"EV-{unique_suffix()}",
        "trigger_fire_potential_index_id": trigger_fire_potential_index_id,
        "forecast_onset_at": forecast_onset_at,
        "forecast_all_clear_at": forecast_all_clear_at,
    }
    payload.update(extra)
    return payload


def scope_payload(expected_psps_event_version, **extra):
    payload = {"expected_psps_event_version": expected_psps_event_version}
    payload.update(extra)
    return payload


def exclude_payload(exclusion_justification="held out for switching constraints", **extra):
    payload = {"exclusion_justification": exclusion_justification}
    payload.update(extra)
    return payload


def cancel_payload(cancellation_reason="forecast downgraded", **extra):
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(extra)
    return payload


def activation_payload(requested_resource_center_ids=None, **extra):
    payload = {}
    if requested_resource_center_ids is not None:
        payload["requested_resource_center_ids"] = requested_resource_center_ids
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Notifications (PRD §3.5)
# --------------------------------------------------------------------------
def notification_batch_payload(
    psps_event_id,
    scheduled_send_at,
    stage=NotificationStage.ADVANCE_48H.value,
    **extra,
):
    payload = {
        "psps_event_id": psps_event_id,
        "stage": stage,
        "scheduled_send_at": scheduled_send_at,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Mitigation portfolio (PRD §3.3)
# --------------------------------------------------------------------------
def mitigation_project_payload(
    circuit_id,
    project_code=None,
    program_type=ProgramType.COVERED_CONDUCTOR.value,
    plan_year=2026,
    planned_miles=4.0,
    unit_cost_per_mile_cents=1250000,
    **extra,
):
    payload = {
        "project_code": project_code or f"MP-{unique_suffix()}",
        "circuit_id": circuit_id,
        "program_type": program_type,
        "plan_year": plan_year,
        "planned_miles": planned_miles,
        "unit_cost_per_mile_cents": unit_cost_per_mile_cents,
    }
    payload.update(extra)
    return payload


def project_review_payload(decision, review_note=None, **extra):
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    payload.update(extra)
    return payload


def record_completion_payload(
    completed_miles_delta, completion_date, expected_circuit_version, **extra
):
    payload = {
        "completed_miles_delta": completed_miles_delta,
        "completion_date": completion_date,
        "expected_circuit_version": expected_circuit_version,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Patrols and damage assessment (PRD §3.7)
# --------------------------------------------------------------------------
def patrol_assignment_payload(
    psps_event_id,
    circuit_id,
    window_start_at,
    window_end_at,
    patrol_lead_user_id="crew_lead_1",
    patrol_mode=PatrolMode.GROUND.value,
    **extra,
):
    payload = {
        "psps_event_id": psps_event_id,
        "circuit_id": circuit_id,
        "patrol_mode": patrol_mode,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "patrol_lead_user_id": patrol_lead_user_id,
    }
    payload.update(extra)
    return payload


def complete_patrol_payload(miles_patrolled=0.0, **extra):
    payload = {"miles_patrolled": miles_patrolled}
    payload.update(extra)
    return payload


def damage_finding_payload(
    patrol_assignment_id,
    severity,
    description="conductor abrasion noted at span 14",
    requires_repair=False,
    **extra,
):
    payload = {
        "patrol_assignment_id": patrol_assignment_id,
        "severity": severity,
        "description": description,
        "requires_repair": requires_repair,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Community resource centers (PRD §3.6)
# --------------------------------------------------------------------------
def resource_center_payload(
    district_code="D-NORTH",
    site_capacity=10,
    resource_center_code=None,
    accessibility_certified=None,
    **extra,
):
    payload = {
        "resource_center_code": resource_center_code or f"CRC-{unique_suffix()}",
        "district_code": district_code,
        "site_capacity": site_capacity,
        "accessibility_certified": accessibility_certified,
    }
    payload = _drop_none(payload)
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Regulatory plan filings (PRD §3.9)
# --------------------------------------------------------------------------
def plan_filing_payload(plan_year=2026, filing_code=None, **extra):
    payload = {
        "filing_code": filing_code or f"WMP-{unique_suffix()}",
        "plan_year": plan_year,
    }
    payload.update(extra)
    return payload


def filing_review_payload(review_track, decision, deficiency_note=None, **extra):
    payload = {"review_track": review_track, "decision": decision}
    if deficiency_note is not None:
        payload["deficiency_note"] = deficiency_note
    payload.update(extra)
    return payload
