"""Payload builders. Every field name and default matches the PRD narrative.

Only the fields the PRD marks required are emitted by default; optional
fields are added by keyword override.
"""

from typing import Any, Dict, List, Optional

# --------------------------------------------------------------- reference data

CANONICAL_CLOCK = "2026-01-05T00:00:00Z"


def pollutant_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": "PM25",
        "averaging_period_hours": 24,
        "standard_form": "ANNUAL_MEAN",
        "primary_standard_value": 9.0,
        "design_value_years": 3,
        "completeness_threshold_pct": 75.0,
        "rounding_decimals": 1,
    }
    payload.update(overrides)
    return payload


def reference_method_payload(pollutant_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "pollutant_id": pollutant_id,
        "method_code": "RFPS-0617-001",
        "designation_type": "FRM",
        "effective_from": "2020-01-01T00:00:00Z",
        "max_span_drift_pct": 5.0,
        "zero_drift_limit": 1.5,
        "required_span_check_interval_days": 14,
        "required_calibration_interval_days": 365,
    }
    payload.update(overrides)
    return payload


def network_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "State Ambient Network",
        "agency_code": "AQ01",
        "metropolitan_population": 1200000,
    }
    payload.update(overrides)
    return payload


def site_payload(network_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "network_id": network_id,
        "site_code": "S-001",
        "site_type": "POPULATION_ORIENTED",
        "latitude": 39.75,
        "longitude": -104.99,
        "population_served": 400000,
        "probe_height_m": 4.0,
        "distance_to_roadway_m": 25.0,
        "distance_to_obstruction_m": 12.0,
        "obstruction_height_m": 6.0,
        "distance_to_source_m": 0.0,
    }
    payload.update(overrides)
    return payload


def monitor_payload(site_id: str, reference_method_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "reference_method_id": reference_method_id,
        "poc": 1,
        "is_primary_for_design_value": True,
        "installed_at": "2022-12-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def span_check_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "event_type": "SPAN_CHECK",
        "performed_at": "2026-01-02T00:00:00Z",
        "span_drift_pct": 2.0,
    }
    payload.update(overrides)
    return payload


def zero_check_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "event_type": "ZERO_CHECK",
        "performed_at": "2026-01-02T00:00:00Z",
        "zero_drift_value": 0.5,
    }
    payload.update(overrides)
    return payload


def data_batch_payload(monitor_id: str, year: int, quarter: int, **overrides) -> Dict[str, Any]:
    payload = {
        "monitor_id": monitor_id,
        "year": year,
        "quarter": quarter,
        "scheduled_hour_count": 2160,
        "quarterly_mean_concentration": 9.0,
    }
    payload.update(overrides)
    return payload


def invalidation_payload(
    start_hour_index: int,
    end_hour_index: int,
    invalidation_code: str,
    expected_data_batch_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "start_hour_index": start_hour_index,
        "end_hour_index": end_hour_index,
        "invalidation_code": invalidation_code,
        "expected_data_batch_version": expected_data_batch_version,
    }
    payload.update(overrides)
    return payload


def demonstration_payload(site_id: str, pollutant_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "pollutant_id": pollutant_id,
        "event_type": "WILDFIRE",
        "event_start_date": "2024-08-12T00:00:00Z",
        "event_end_date": "2024-08-19T00:00:00Z",
        "narrative": "Regional wildfire smoke plume over the metropolitan area",
        "clear_causal_relationship": True,
    }
    payload.update(overrides)
    return payload


def exclusion_payload(
    data_batch_id: str, start_hour_index: int, end_hour_index: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "data_batch_id": data_batch_id,
        "start_hour_index": start_hour_index,
        "end_hour_index": end_hour_index,
    }
    payload.update(overrides)
    return payload


def design_value_payload(
    site_id: str,
    pollutant_id: str,
    period_end_year: int,
    variant: str,
    expected_monitoring_site_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "pollutant_id": pollutant_id,
        "period_end_year": period_end_year,
        "variant": variant,
        "expected_monitoring_site_version": expected_monitoring_site_version,
    }
    payload.update(overrides)
    return payload


def package_payload(network_id: str, pollutant_id: str, year: int, **overrides) -> Dict[str, Any]:
    payload = {"network_id": network_id, "pollutant_id": pollutant_id, "year": year}
    payload.update(overrides)
    return payload


def assessment_payload(network_id: str, cycle_year: int, **overrides) -> Dict[str, Any]:
    payload = {"network_id": network_id, "cycle_year": cycle_year}
    payload.update(overrides)
    return payload


def change_request_payload(
    site_id: str, request_type: str, assessment_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "site_id": site_id,
        "request_type": request_type,
        "justification": "Redundant with the co-located regional site",
        "assessment_id": assessment_id,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- quarter sets

#: The twelve quarters of PRD 3.7's worked example: quarterly means of
#: 9.2, 9.4, 9.3 and 9.1 in 2023; 9.0, 9.1, 9.2 and 8.9 in 2024; and
#: 8.9, 9.0, 9.1 and 8.8 in 2025, with the third quarter of 2024 also
#: carrying an event-adjusted mean of 7.9.
WORKED_EXAMPLE_QUARTERS: List[Dict[str, Any]] = [
    {"year": 2023, "quarter": 1, "scheduled_hour_count": 2160, "quarterly_mean_concentration": 9.2},
    {"year": 2023, "quarter": 2, "scheduled_hour_count": 2184, "quarterly_mean_concentration": 9.4},
    {"year": 2023, "quarter": 3, "scheduled_hour_count": 2208, "quarterly_mean_concentration": 9.3},
    {"year": 2023, "quarter": 4, "scheduled_hour_count": 2208, "quarterly_mean_concentration": 9.1},
    {"year": 2024, "quarter": 1, "scheduled_hour_count": 2184, "quarterly_mean_concentration": 9.0},
    {"year": 2024, "quarter": 2, "scheduled_hour_count": 2184, "quarterly_mean_concentration": 9.1},
    {
        "year": 2024,
        "quarter": 3,
        "scheduled_hour_count": 2208,
        "quarterly_mean_concentration": 9.2,
        "quarterly_mean_concentration_event_adjusted": 7.9,
    },
    {"year": 2024, "quarter": 4, "scheduled_hour_count": 2208, "quarterly_mean_concentration": 8.9},
    {"year": 2025, "quarter": 1, "scheduled_hour_count": 2160, "quarterly_mean_concentration": 8.9},
    {"year": 2025, "quarter": 2, "scheduled_hour_count": 2184, "quarterly_mean_concentration": 9.0},
    {"year": 2025, "quarter": 3, "scheduled_hour_count": 2208, "quarterly_mean_concentration": 9.1},
    {"year": 2025, "quarter": 4, "scheduled_hour_count": 2208, "quarterly_mean_concentration": 8.8},
]

#: Index of each quarter of WORKED_EXAMPLE_QUARTERS inside the bulk-ingest
#: response array, which preserves request order.
Q_INDEX = {(q["year"], q["quarter"]): i for i, q in enumerate(WORKED_EXAMPLE_QUARTERS)}


def bulk_ingest_payload(monitor_id: str, batches: Optional[List[Dict[str, Any]]] = None):
    return {
        "monitor_id": monitor_id,
        "batches": [dict(b) for b in (batches if batches is not None else WORKED_EXAMPLE_QUARTERS)],
    }
