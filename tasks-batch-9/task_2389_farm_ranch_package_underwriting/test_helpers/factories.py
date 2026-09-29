"""Payload factories — one per entity, input fields only."""

from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "AGENCY_NAME": "Prairie Risk Partners",
    "LICENSE_STATE": "KS",
    "AUTHORITY_LIMIT_CENTS": 5_000_000,
    "INSPECTOR_NAME": "Dana Reyes",
    "REGION_CODE": "KS-CENTRAL",
    "DAILY_CAPACITY_MINUTES": 480,
    "ZONE_CODE": "ZN-1",
    "TOTAL_CAPACITY_CENTS": 200_000_000,
    "LEGAL_NAME": "Kestrel Creek Farms",
    "STATE_CODE": "KS",
    "COUNTY_NAME": "Reno",
    "ACREAGE": 1200,
    "OPERATION_TYPE": "MIXED",
    "TERM_START_DATE": "2026-09-01",
    "TERM_END_DATE": "2027-08-31",
    "DEDUCTIBLE_CENTS": 500_000,
    "DWELLING_DESCRIPTION": "Ranch house",
    "DWELLING_VALUE_CENTS": 40_000_000,
    "DWELLING_AGE_YEARS": 22,
    "DWELLING_CONDITION_GRADE": "B",
}


# --- Reference data ------------------------------------------------------


def create_agent_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "license_state": DEFAULTS["LICENSE_STATE"],
        "appointment_status": "ACTIVE",
        "authority_limit_cents": DEFAULTS["AUTHORITY_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["INSPECTOR_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
        "status": "ACTIVE",
        "daily_capacity_minutes": DEFAULTS["DAILY_CAPACITY_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_cat_capacity_pool_payload(peril: str = "HAIL", **overrides) -> Dict[str, Any]:
    participation = {"HAIL": 0.50, "WIND": 0.30, "WILDFIRE": 0.20}[peril]
    payload = {
        "zone_code": DEFAULTS["ZONE_CODE"],
        "peril": peril,
        "participation_pct": participation,
        "total_capacity_cents": DEFAULTS["TOTAL_CAPACITY_CENTS"],
        "status": "OPEN",
    }
    payload.update(overrides)
    return payload


# --- Account and policy -------------------------------------------------


def create_farm_account_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "county_name": DEFAULTS["COUNTY_NAME"],
        "cat_zone_code": DEFAULTS["ZONE_CODE"],
        "acreage": DEFAULTS["ACREAGE"],
        "operation_type": DEFAULTS["OPERATION_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_farm_policy_payload(account_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "term_start_date": DEFAULTS["TERM_START_DATE"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
    }
    payload.update(overrides)
    return payload


# --- Exposures ----------------------------------------------------------


def create_scheduled_item_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "item_class": "DWELLING",
        "description": DEFAULTS["DWELLING_DESCRIPTION"],
        "valuation_basis": "RC",
        "stated_value_cents": DEFAULTS["DWELLING_VALUE_CENTS"],
        "age_years": DEFAULTS["DWELLING_AGE_YEARS"],
        "condition_grade": DEFAULTS["DWELLING_CONDITION_GRADE"],
    }
    payload.update(overrides)
    return payload


def create_seasonal_item_payload(
    item_class: str = "STORED_CROP",
    stated_value_cents: int = 6_005_000,
    peak_season_value_cents: int = 18_000_000,
    peak_season_start_month: int = 10,
    peak_season_end_month: int = 2,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "item_class": item_class,
        "description": "Milo in bin 4",
        "valuation_basis": "RC",
        "stated_value_cents": stated_value_cents,
        "age_years": 0,
        "condition_grade": "A",
        "peak_season_value_cents": peak_season_value_cents,
        "peak_season_start_month": peak_season_start_month,
        "peak_season_end_month": peak_season_end_month,
    }
    payload.update(overrides)
    return payload


def create_livestock_group_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "species": "CATTLE",
        "head_count": 170,
        "per_head_value_cents": 150_000,
        "limit_basis": "PER_HEAD",
        "peril_scope": "FULL_PERIL",
    }
    payload.update(overrides)
    return payload


def create_liability_exposure_payload(
    exposure_type: str = "GENERAL_FARM", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exposure_type": exposure_type,
        "annual_receipts_cents": 0,
    }
    if exposure_type == "AGRITOURISM":
        payload["annual_visitor_count"] = 800
    payload.update(overrides)
    return payload


def create_labor_profile_payload(
    full_time_count: int = 0, seasonal_count: int = 0, migrant_h2a_count: int = 0, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_time_count": full_time_count,
        "seasonal_count": seasonal_count,
        "migrant_h2a_count": migrant_h2a_count,
    }
    payload.update(overrides)
    return payload


# --- Endorsements -------------------------------------------------------


def create_endorsement_payload(
    expected_policy_version: int,
    form_code: str = "PEAK_SEASON_INCREASE",
    sublimit_cents: int = 12_000_000,
    requested_effective_date: str = "2026-10-01",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "expected_policy_version": expected_policy_version,
        "form_code": form_code,
        "sublimit_cents": sublimit_cents,
        "requested_effective_date": requested_effective_date,
    }
    payload.update(overrides)
    return payload


# --- Loss control -------------------------------------------------------


def create_inspection_payload(
    policy_id: str,
    inspector_id: str,
    inspection_type: str = "INITIAL",
    scheduled_for: str = "2026-08-16T09:00:00Z",
    duration_minutes: int = 120,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "policy_id": policy_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_for": scheduled_for,
        "duration_minutes": duration_minutes,
    }
    payload.update(overrides)
    return payload


def finding(severity: str, description: str, due_date: str) -> Dict[str, Any]:
    return {"severity": severity, "description": description, "due_date": due_date}


def complete_inspection_payload(findings_summary: str, findings=None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "findings_summary": findings_summary,
        "findings": list(findings or []),
    }
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULTS",
    "create_agent_payload",
    "create_inspector_payload",
    "create_cat_capacity_pool_payload",
    "create_farm_account_payload",
    "create_farm_policy_payload",
    "create_scheduled_item_payload",
    "create_seasonal_item_payload",
    "create_livestock_group_payload",
    "create_liability_exposure_payload",
    "create_labor_profile_payload",
    "create_endorsement_payload",
    "create_inspection_payload",
    "finding",
    "complete_inspection_payload",
]
