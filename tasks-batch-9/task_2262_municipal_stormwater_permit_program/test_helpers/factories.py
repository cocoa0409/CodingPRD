"""Request payload builders.

Each builder returns a payload that satisfies every shape rule the PRD states
for that endpoint, so that a test only has to name the fields it actually cares
about.  Keyword overrides are merged over the defaults; passing ``None`` for a
key removes it from the payload, which is how tests build the
deliberately-incomplete bodies the shape rules reject.
"""

from typing import Any, Dict

from .constants import DEFAULT_ERU_SQFT


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            del payload[key]
        else:
            payload[key] = value
    return payload


# --------------------------------------------------------------------------
# Permit terms and control measures (PRD §3.1)
# --------------------------------------------------------------------------


def permit_term_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "permit_number": "MS4-2026-A",
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "tmdl_applicable": False,
            "eru_sqft": DEFAULT_ERU_SQFT,
        },
        overrides,
    )


def tmdl_permit_term_payload(**overrides: Any) -> Dict[str, Any]:
    return permit_term_payload(
        **_merge(
            {
                "tmdl_applicable": True,
                "tmdl_pollutant": "TOTAL_PHOSPHORUS",
                "tmdl_wla_lb_per_year": 50.00,
            },
            overrides,
        )
    )


def control_measure_payload(term_id: str, measure_code: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "permit_term_id": term_id,
            "measure_code": measure_code,
            "measurable_goal_target": 10.00,
        },
        overrides,
    )


def report_progress_payload(measurable_goal_actual: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"measurable_goal_actual": measurable_goal_actual}, overrides)


# --------------------------------------------------------------------------
# Outfalls and observations (PRD §3.2, §3.7)
# --------------------------------------------------------------------------


def outfall_payload(term_id: str, outfall_code: str = "OF-01", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "permit_term_id": term_id,
            "outfall_code": outfall_code,
            "receiving_water": "Mill Creek",
            "drainage_area_acres": 40.00,
            "priority_tier": "HIGH",
            "baseline_concentration_mg_per_l": 0.40,
            "design_runoff_kl": 1000.00,
            "sweeping_capacity_lane_miles_per_month": 40.00,
        },
        overrides,
    )


def screening_payload(observed_at: str = "2026-08-01T08:00:00Z", **overrides: Any) -> Dict[str, Any]:
    """A dry-weather screening whose indicator panel reads CLEAR."""
    return _merge(
        {
            "observation_type": "DRY_WEATHER_SCREENING",
            "observed_at": observed_at,
            "dry_weather_flow_present": True,
            "indicator_bacteria_mpn": 100.0,
            "indicator_surfactant_mg_per_l": 0.10,
            "indicator_ammonia_mg_per_l": 0.20,
        },
        overrides,
    )


def suspect_screening_payload(
    observed_at: str = "2026-08-01T08:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    """A dry-weather screening whose panel exceeds two of the three limits."""
    return screening_payload(
        observed_at,
        **_merge(
            {
                "indicator_bacteria_mpn": 5000.0,
                "indicator_surfactant_mg_per_l": 0.80,
                "indicator_ammonia_mg_per_l": 0.20,
            },
            overrides,
        ),
    )


def sample_payload(
    observed_at: str = "2026-08-01T08:00:00Z",
    pollutant_concentration_mg_per_l: float = 0.40,
    runoff_volume_kl: float = 1000.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "observation_type": "WET_WEATHER_SAMPLE",
            "observed_at": observed_at,
            "pollutant_concentration_mg_per_l": pollutant_concentration_mg_per_l,
            "runoff_volume_kl": runoff_volume_kl,
        },
        overrides,
    )


def validate_observation_payload(decision: str = "VALIDATE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def sweeping_run_payload(
    run_start_date: str = "2026-08-01",
    run_end_date: str = "2026-08-10",
    lane_miles_swept: float = 10.00,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "run_start_date": run_start_date,
            "run_end_date": run_end_date,
            "lane_miles_swept": lane_miles_swept,
        },
        overrides,
    )


def load_assessment_payload(
    variant: str = "FINAL", reporting_year: int = 2026, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"variant": variant, "reporting_year": reporting_year}, overrides)


# --------------------------------------------------------------------------
# Illicit discharge cases (PRD §3.3)
# --------------------------------------------------------------------------


def start_tracing_payload(trace_method: str = "DYE_TEST", **overrides: Any) -> Dict[str, Any]:
    return _merge({"trace_method": trace_method}, overrides)


def identify_source_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "source_description": "Failed grease interceptor on the north lateral.",
            "responsible_party": "Northside Diner LLC",
        },
        overrides,
    )


def reopen_tracing_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Dye test did not reproduce the discharge."}, overrides)


def resolve_case_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"resolution_note": "Lateral disconnected and verified dry."}, overrides)


# --------------------------------------------------------------------------
# Construction sites (PRD §3.4)
# --------------------------------------------------------------------------


def construction_site_payload(
    term_id: str, site_name: str = "Riverbend Phase 1", disturbed_acres: float = 3.00, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "permit_term_id": term_id,
            "site_name": site_name,
            "operator_name": "Riverbend Builders",
            "disturbed_acres": disturbed_acres,
        },
        overrides,
    )


def submit_esc_plan_payload(esc_plan_reference: str = "ESC-A-1", **overrides: Any) -> Dict[str, Any]:
    return _merge({"esc_plan_reference": esc_plan_reference}, overrides)


def esc_review_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def stop_work_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Sediment discharge observed at the perimeter."}, overrides)


def release_stop_work_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"corrective_action_note": "Perimeter controls rebuilt and inspected."}, overrides)


def close_site_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"final_stabilization_note": "Permanent vegetation established."}, overrides)


# --------------------------------------------------------------------------
# Permanent controls and inspections (PRD §3.5)
# --------------------------------------------------------------------------


def facility_payload(site_id: str, ownership: str = "PRIVATE", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "construction_site_id": site_id,
            "facility_type": "BIORETENTION",
            "ownership": ownership,
            "design_capacity_cf": 5000.00,
            "service_area_acres": 2.50,
        },
        overrides,
    )


def record_agreement_payload(
    recorded_at: str = "2026-08-01T00:00:00Z",
    inspection_interval_months: int = 12,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "agreement_reference": "AGR-0001",
            "recorded_at": recorded_at,
            "inspection_interval_months": inspection_interval_months,
        },
        overrides,
    )


def esc_inspection_payload(
    site_id: str,
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "inspection_type": "CONSTRUCTION_ESC",
            "construction_site_id": site_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def maintenance_inspection_payload(
    facility_id: str,
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "inspection_type": "POST_CONSTRUCTION_MAINTENANCE",
            "post_construction_facility_id": facility_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def finding_payload(severity: str = "MINOR", **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"severity": severity, "description": f"{severity} deficiency observed."},
        overrides,
    )


# --------------------------------------------------------------------------
# Enforcement actions (PRD §3.6)
# --------------------------------------------------------------------------


def enforcement_action_payload(
    action_type: str = "NOTICE_OF_VIOLATION", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"action_type": action_type}, overrides)


def escalate_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def close_enforcement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"compliance_note": "Operator documented full compliance."}, overrides)


def rescind_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Action issued against the wrong subject."}, overrides)


# --------------------------------------------------------------------------
# Utility accounts, billing and credits (PRD §3.8)
# --------------------------------------------------------------------------


def account_payload(
    term_id: str,
    parcel_id: str = "PCL-0001",
    parcel_class: str = "RESIDENTIAL_SINGLE",
    impervious_area_sqft: float = 3000.0,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "permit_term_id": term_id,
            "parcel_id": parcel_id,
            "owner_name": "A. Owner",
            "parcel_class": parcel_class,
            "impervious_area_sqft": impervious_area_sqft,
        },
        overrides,
    )


def impervious_update_payload(
    impervious_area_sqft: float, expected_stormwater_account_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "impervious_area_sqft": impervious_area_sqft,
            "expected_stormwater_account_version": expected_stormwater_account_version,
        },
        overrides,
    )


def billing_run_payload(
    run_type: str = "FINAL",
    period_start: str = "2026-01-01",
    period_end: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"run_type": run_type, "period_start": period_start, "period_end": period_end},
        overrides,
    )


def credit_application_payload(
    account_id: str,
    expected_stormwater_account_version: int,
    requested_credit_pct: float = 0.2000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "stormwater_account_id": account_id,
            "requested_credit_pct": requested_credit_pct,
            "bmp_description": "On-site bioretention cell treating the parking court.",
            "expected_stormwater_account_version": expected_stormwater_account_version,
        },
        overrides,
    )


def credit_review_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def credit_resubmit_payload(
    requested_credit_pct: float = 0.1500, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "requested_credit_pct": requested_credit_pct,
            "bmp_description": "Revised bioretention cell with underdrain.",
        },
        overrides,
    )


def credit_revoke_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": "Facility taken out of service."}, overrides)


# --------------------------------------------------------------------------
# Annual reports (PRD §3.9)
# --------------------------------------------------------------------------


def annual_report_payload(
    term_id: str,
    reporting_period_start: str = "2026-01-01",
    reporting_period_end: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "permit_term_id": term_id,
            "reporting_period_start": reporting_period_start,
            "reporting_period_end": reporting_period_end,
        },
        overrides,
    )


def compile_report_payload(expected_permit_term_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_permit_term_version": expected_permit_term_version}, overrides)


def certify_report_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "certification_statement": (
                "I certify under penalty of law that this report is true, accurate and complete."
            )
        },
        overrides,
    )
