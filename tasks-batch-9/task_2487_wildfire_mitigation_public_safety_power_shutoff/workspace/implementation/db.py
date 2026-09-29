"""In-memory data store.

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid

from flask import g

import clock
from response import fmt_ts

_seq = itertools.count(1)

# ---------------------------------------------------------------- collections
circuits = {}
weather_stations = {}
weather_observations = {}
fire_potential_indices = {}
psps_events = {}
event_scopes = {}
customers = {}
notification_batches = {}
notification_records = {}
mitigation_projects = {}
patrol_assignments = {}
damage_findings = {}
resource_centers = {}
plan_filings = {}


def new_row(versioned=True):
    stamp = clock.now()
    row = {
        "id": str(uuid.uuid4()),
        "_seq": next(_seq),
        "_raw": {},
        "created_at": stamp,
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
        # A row created by this request already reads version 1; a cascade that
        # touches it later in the same request must not push it to 2.
        seen = _touched()
        if seen is not None:
            seen.add(row["id"])
    return row


def _touched():
    try:
        return g.touched
    except Exception:  # pragma: no cover - outside a request context
        return None


def touch(row):
    """Bump updated_at/version at most once per request for a given row."""
    if "version" not in row:
        return
    seen = _touched()
    key = row["id"]
    if seen is not None:
        if key in seen:
            row["updated_at"] = clock.now()
            return
        seen.add(key)
    row["version"] += 1
    row["updated_at"] = clock.now()


def in_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def newest(rows):
    if not rows:
        return None
    return max(rows, key=lambda r: (r["created_at"], r["_seq"]))


def set_dt(row, field, value, raw_value=None):
    row[field] = value
    if raw_value is None:
        row["_raw"].pop(field, None)
    else:
        row["_raw"][field] = raw_value


def dt_out(row, field):
    value = row.get(field)
    if value is None:
        return None
    raw_value = row.get("_raw", {}).get(field)
    if raw_value is not None:
        return raw_value
    return fmt_ts(value)


def _common(row, out, versioned=True):
    out["created_at"] = fmt_ts(row["created_at"])
    if versioned:
        out["updated_at"] = fmt_ts(row["updated_at"])
        out["version"] = row["version"]
    return out


# ------------------------------------------------------------- serialization
def circuit_out(row):
    out = {
        "id": row["id"],
        "circuit_code": row["circuit_code"],
        "district_code": row["district_code"],
        "hftd_tier": row["hftd_tier"],
        "overhead_miles": row["overhead_miles"],
        "equipment_condition_index": row["equipment_condition_index"],
        "inspection_cycle_months": row["inspection_cycle_months"],
        "last_inspection_completed_at": dt_out(row, "last_inspection_completed_at"),
        "upstream_circuit_id": row["upstream_circuit_id"],
        "fast_trip_enabled": row["fast_trip_enabled"],
        "covered_conductor_miles": row["covered_conductor_miles"],
        "underground_miles": row["underground_miles"],
        "hardened_fraction": row["hardened_fraction"],
        "customer_count": row["customer_count"],
        "medical_baseline_count": row["medical_baseline_count"],
        "critical_facility_count": row["critical_facility_count"],
        "energization_state": row["energization_state"],
        "risk_posture": row["risk_posture"],
        "latest_forecast_fpi_score": row["latest_forecast_fpi_score"],
        "latest_forecast_fpi_tier": row["latest_forecast_fpi_tier"],
    }
    return _common(row, out)


def weather_station_out(row):
    out = {
        "id": row["id"],
        "station_code": row["station_code"],
        "circuit_id": row["circuit_id"],
        "elevation_ft": row["elevation_ft"],
        "representativeness_weight": row["representativeness_weight"],
        "telemetry_status": row["telemetry_status"],
        "observation_count": row["observation_count"],
        "last_observation_at": dt_out(row, "last_observation_at"),
    }
    return _common(row, out)


def weather_observation_out(row):
    out = {
        "id": row["id"],
        "weather_station_id": row["weather_station_id"],
        "observed_at": dt_out(row, "observed_at"),
        "wind_gust_mph": row["wind_gust_mph"],
        "relative_humidity_pct": row["relative_humidity_pct"],
        "temperature_f": row["temperature_f"],
        "dead_fuel_moisture_pct": row["dead_fuel_moisture_pct"],
    }
    return _common(row, out, versioned=False)


def fire_potential_index_out(row):
    out = {
        "id": row["id"],
        "circuit_id": row["circuit_id"],
        "forecast_date": row["forecast_date"],
        "computation_variant": row["computation_variant"],
        "contributing_station_count": row["contributing_station_count"],
        "effective_wind_gust_mph": row["effective_wind_gust_mph"],
        "effective_relative_humidity_pct": row["effective_relative_humidity_pct"],
        "effective_dead_fuel_moisture_pct": row["effective_dead_fuel_moisture_pct"],
        "wind_component": row["wind_component"],
        "dryness_component": row["dryness_component"],
        "terrain_component": row["terrain_component"],
        "equipment_component": row["equipment_component"],
        "inspection_overdue": row["inspection_overdue"],
        "hardened_fraction_applied": row["hardened_fraction_applied"],
        "fpi_score": row["fpi_score"],
        "fpi_tier": row["fpi_tier"],
    }
    return _common(row, out, versioned=False)


def psps_event_out(row):
    out = {
        "id": row["id"],
        "event_code": row["event_code"],
        "trigger_fire_potential_index_id": row["trigger_fire_potential_index_id"],
        "forecast_onset_at": dt_out(row, "forecast_onset_at"),
        "forecast_all_clear_at": dt_out(row, "forecast_all_clear_at"),
        "scope_status": row["scope_status"],
        "notification_status": row["notification_status"],
        "cancellation_reason": row["cancellation_reason"],
        "actual_de_energized_at": dt_out(row, "actual_de_energized_at"),
        "actual_restored_at": dt_out(row, "actual_restored_at"),
        "duration_hours": row["duration_hours"],
        "benefit_variant": row["benefit_variant"],
        "confirmed_scope_count": row["confirmed_scope_count"],
        "excluded_scope_count": row["excluded_scope_count"],
        "impacted_customer_count": row["impacted_customer_count"],
        "medical_baseline_customer_count": row["medical_baseline_customer_count"],
        "critical_facility_count": row["critical_facility_count"],
        "ignition_risk_avoided_score": row["ignition_risk_avoided_score"],
        "customer_impact_score": row["customer_impact_score"],
        "crc_capacity_required": row["crc_capacity_required"],
        "crc_capacity_served": row["crc_capacity_served"],
        "crc_mitigation_credit": row["crc_mitigation_credit"],
        "adjusted_customer_impact_score": row["adjusted_customer_impact_score"],
        "net_benefit_ratio": row["net_benefit_ratio"],
    }
    return _common(row, out)


def event_scope_out(row):
    out = {
        "id": row["id"],
        "psps_event_id": row["psps_event_id"],
        "circuit_id": row["circuit_id"],
        "inclusion_basis": row["inclusion_basis"],
        "scope_status": row["scope_status"],
        "exclusion_justification": row["exclusion_justification"],
        "customer_count_snapshot": row["customer_count_snapshot"],
        "fpi_score_applied": row["fpi_score_applied"],
        "ignition_risk_term": row["ignition_risk_term"],
        "restored_at": dt_out(row, "restored_at"),
    }
    return _common(row, out)


def customer_out(row):
    out = {
        "id": row["id"],
        "account_number": row["account_number"],
        "circuit_id": row["circuit_id"],
        "customer_class": row["customer_class"],
        "medical_baseline": row["medical_baseline"],
        "preferred_language": row["preferred_language"],
        "notification_channels": list(row["notification_channels"]),
        "accessibility_needs": list(row["accessibility_needs"]),
        "address_zone_code": row["address_zone_code"],
        "notification_tier": row["notification_tier"],
    }
    return _common(row, out)


def notification_batch_out(row):
    out = {
        "id": row["id"],
        "psps_event_id": row["psps_event_id"],
        "stage": row["stage"],
        "scheduled_send_at": dt_out(row, "scheduled_send_at"),
        "status": row["status"],
        "dispatched_at": dt_out(row, "dispatched_at"),
        "lead_time_minutes": row["lead_time_minutes"],
        "target_count": row["target_count"],
        "delivered_count": row["delivered_count"],
        "unreachable_count": row["unreachable_count"],
    }
    return _common(row, out)


def notification_record_out(row):
    out = {
        "id": row["id"],
        "notification_batch_id": row["notification_batch_id"],
        "customer_id": row["customer_id"],
        "attempt_order": row["attempt_order"],
        "language_used": row["language_used"],
        "channel_used": row["channel_used"],
        "accessibility_format": row["accessibility_format"],
        "delivery_status": row["delivery_status"],
    }
    return _common(row, out, versioned=False)


def mitigation_project_out(row):
    out = {
        "id": row["id"],
        "project_code": row["project_code"],
        "circuit_id": row["circuit_id"],
        "program_type": row["program_type"],
        "plan_year": row["plan_year"],
        "planned_miles": row["planned_miles"],
        "unit_cost_per_mile_cents": row["unit_cost_per_mile_cents"],
        "budget_cents": row["budget_cents"],
        "completed_miles": row["completed_miles"],
        "risk_reduction_score": row["risk_reduction_score"],
        "status": row["status"],
        "review_round": row["review_round"],
        "last_revision_reviewer_user_id": row["last_revision_reviewer_user_id"],
        "last_review_note": row["last_review_note"],
    }
    return _common(row, out)


def patrol_assignment_out(row):
    out = {
        "id": row["id"],
        "psps_event_id": row["psps_event_id"],
        "circuit_id": row["circuit_id"],
        "patrol_mode": row["patrol_mode"],
        "window_start_at": dt_out(row, "window_start_at"),
        "window_end_at": dt_out(row, "window_end_at"),
        "patrol_lead_user_id": row["patrol_lead_user_id"],
        "status": row["status"],
        "started_at": dt_out(row, "started_at"),
        "completed_at": dt_out(row, "completed_at"),
        "miles_patrolled": row["miles_patrolled"],
        "damage_finding_count": row["damage_finding_count"],
        "ignition_risk_finding_count": row["ignition_risk_finding_count"],
    }
    return _common(row, out)


def damage_finding_out(row):
    out = {
        "id": row["id"],
        "patrol_assignment_id": row["patrol_assignment_id"],
        "severity": row["severity"],
        "description": row["description"],
        "requires_repair": row["requires_repair"],
        "found_at": dt_out(row, "found_at"),
    }
    return _common(row, out, versioned=False)


def resource_center_out(row):
    out = {
        "id": row["id"],
        "resource_center_code": row["resource_center_code"],
        "district_code": row["district_code"],
        "site_capacity": row["site_capacity"],
        "accessibility_certified": row["accessibility_certified"],
        "status": row["status"],
        "psps_event_id": row["psps_event_id"],
        "activated_at": dt_out(row, "activated_at"),
        "demobilized_at": dt_out(row, "demobilized_at"),
        "last_served_all_clear_at": dt_out(row, "last_served_all_clear_at"),
        "activation_order": row["activation_order"],
    }
    return _common(row, out)


def plan_filing_out(row):
    out = {
        "id": row["id"],
        "filing_code": row["filing_code"],
        "plan_year": row["plan_year"],
        "status": row["status"],
        "safety_review_state": row["safety_review_state"],
        "fiscal_review_state": row["fiscal_review_state"],
        "safety_reviewer_user_id": row["safety_reviewer_user_id"],
        "fiscal_reviewer_user_id": row["fiscal_reviewer_user_id"],
        "deficiency_round_count": row["deficiency_round_count"],
        "last_deficiency_note": row["last_deficiency_note"],
        "qualifying_project_count": row["qualifying_project_count"],
        "covered_conductor_miles_reported": row["covered_conductor_miles_reported"],
        "underground_miles_reported": row["underground_miles_reported"],
        "psps_event_count": row["psps_event_count"],
        "customer_minutes_interrupted": row["customer_minutes_interrupted"],
        "avg_notification_lead_minutes": row["avg_notification_lead_minutes"],
        "compliance_score": row["compliance_score"],
    }
    return _common(row, out)
