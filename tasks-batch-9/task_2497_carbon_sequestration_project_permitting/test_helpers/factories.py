"""Payload factories — one per entity, carrying only client-supplied fields."""

from .constants import (
    ALPHA_PERMIT,
    ALPHA_PROJECT,
    DEFAULT_INJECTION_YEARS,
    LEASE_TERM_END,
    LEASE_TERM_START,
    M1_MODEL_PARAMS,
)
from .test_users import LANDOWNER_1_USER_ID


def create_storage_project_payload(**overrides) -> dict:
    payload = dict(ALPHA_PROJECT)
    payload.update(overrides)
    return payload


def create_geologic_model_payload(project_id, expected_project_version, **overrides):
    payload = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
        "supersedes_model_id": None,
    }
    payload.update(M1_MODEL_PARAMS)
    payload.update(overrides)
    return payload


def run_plume_simulation_payload(injection_years=DEFAULT_INJECTION_YEARS, **overrides):
    payload = {"injection_years": injection_years}
    payload.update(overrides)
    return payload


def create_legacy_wellbore_payload(project_id, api_number, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "api_number": api_number,
        "distance_from_injector_km": 0.5,
        "total_depth_m": 2000,
        "penetrates_seal": True,
        "plug_condition": "OPEN_HOLE",
        "plug_record_available": False,
    }
    payload.update(overrides)
    return payload


def schedule_corrective_action_payload(window_start, window_end, **overrides) -> dict:
    payload = {"window_start": window_start, "window_end": window_end}
    payload.update(overrides)
    return payload


def create_pore_space_tract_payload(project_id, tract_label, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "tract_label": tract_label,
        "acreage": 1000,
        "ownership_pct": 100,
        "landowner_user_id": LANDOWNER_1_USER_ID,
    }
    payload.update(overrides)
    return payload


def lease_offer_payload(
    expected_tract_version, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5, **overrides
) -> dict:
    payload = {
        "expected_tract_version": expected_tract_version,
        "bonus_per_acre_usd": bonus_per_acre_usd,
        "royalty_rate_pct": royalty_rate_pct,
    }
    payload.update(overrides)
    return payload


def accept_offer_payload(
    lease_term_start=LEASE_TERM_START, lease_term_end=LEASE_TERM_END, **overrides
) -> dict:
    payload = {
        "response": "ACCEPT",
        "lease_term_start": lease_term_start,
        "lease_term_end": lease_term_end,
    }
    payload.update(overrides)
    return payload


def counter_offer_payload(counter_bonus_per_acre_usd, **overrides) -> dict:
    payload = {
        "response": "COUNTER",
        "counter_bonus_per_acre_usd": counter_bonus_per_acre_usd,
    }
    payload.update(overrides)
    return payload


def create_injection_well_permit_payload(project_id, geologic_model_id, **overrides):
    payload = {"project_id": project_id, "geologic_model_id": geologic_model_id}
    payload.update(ALPHA_PERMIT)
    payload.update(overrides)
    return payload


def record_mit_payload(
    test_type="ANNULUS_PRESSURE", annulus_pressure_loss_psi=2.50, **overrides
) -> dict:
    payload = {"test_type": test_type}
    if test_type == "ANNULUS_PRESSURE":
        payload["annulus_pressure_loss_psi"] = annulus_pressure_loss_psi
    payload.update(overrides)
    return payload


def advance_construction_payload(to_construction_status, **overrides) -> dict:
    payload = {"to_construction_status": to_construction_status}
    payload.update(overrides)
    return payload


def report_injection_period_payload(
    period_start, period_end, mass_injected_tonnes, **overrides
) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
        "mass_injected_tonnes": mass_injected_tonnes,
    }
    payload.update(overrides)
    return payload


def create_monitoring_plan_payload(project_id, plan_label="MRV-1", **overrides) -> dict:
    payload = {"project_id": project_id, "plan_label": plan_label}
    payload.update(overrides)
    return payload


def create_monitoring_method_payload(
    domain,
    technique,
    detection_threshold_tpy,
    frequency_per_year,
    spatial_coverage_pct,
    **overrides,
) -> dict:
    payload = {
        "domain": domain,
        "technique": technique,
        "detection_threshold_tpy": detection_threshold_tpy,
        "frequency_per_year": frequency_per_year,
        "spatial_coverage_pct": spatial_coverage_pct,
    }
    payload.update(overrides)
    return payload


def create_financial_instrument_payload(
    project_id, instrument_type="TRUST_FUND", face_amount_usd=26000000, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "instrument_type": instrument_type,
        "face_amount_usd": face_amount_usd,
    }
    payload.update(overrides)
    return payload


def allocate_payload(expected_instrument_version, **overrides) -> dict:
    payload = {"expected_instrument_version": expected_instrument_version}
    payload.update(overrides)
    return payload


def create_tax_credit_claim_payload(
    project_id, monitoring_plan_id, tax_year=2027, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "monitoring_plan_id": monitoring_plan_id,
        "tax_year": tax_year,
    }
    payload.update(overrides)
    return payload


def create_remediation_order_payload(
    project_id, trigger_type="PLUME_EXCURSION", severity="MAJOR", **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "trigger_type": trigger_type,
        "severity": severity,
        "narrative": "Monitoring detected an event requiring an emergency order.",
    }
    payload.update(overrides)
    return payload
