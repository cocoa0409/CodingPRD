"""Payload factories — one per entity, input fields only.

Each factory fills sensible defaults and accepts ``**overrides``. Foreign-key
fields that must reference a real resource are required positional arguments.
"""
from .constants import TEST_DEFAULTS


def create_dwelling_payload(**overrides) -> dict:
    defaults = {
        "address": "1 Test St",
        "year_built": 1965,
        "conditioned_area_sqft": 1500,
        "foundation_type": "SLAB",
        "heating_fuel_type": "GAS",
    }
    defaults.update(overrides)
    return defaults


def create_wap_application_payload(dwelling_id: str, **overrides) -> dict:
    defaults = {
        "dwelling_id": dwelling_id,
        "household_size": 3,
        "annual_gross_income_cents": 4_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(dwelling_id: str, **overrides) -> dict:
    defaults = {
        "dwelling_id": dwelling_id,
        "program_track": "UTILITY",
        "rebate_budget_cap_cents": TEST_DEFAULTS["REBATE_BUDGET_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(job_id: str, **overrides) -> dict:
    defaults = {"job_id": job_id}
    defaults.update(overrides)
    return defaults


def create_scope_item_payload(job_id: str, audit_id: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "audit_id": audit_id,
        "category": "ATTIC_INSULATION",
        "area_sqft": 1000,
        "target_r_value": 38,
        "estimated_cost_cents": 300_000,
        "estimated_savings_kwh": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_diagnostic_test_payload(job_id: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "kind": "BLOWER_DOOR",
        "stage": "BASELINE",
        "cfm_measured": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "crew_size": 3,
        "skills": ["ATTIC_INSULATION"],
        "capacity_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(job_id: str, crew_id: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "crew_id": crew_id,
        "scheduled_start_date": TEST_DEFAULTS["DEFAULT_START_DATE"],
        "scheduled_end_date": TEST_DEFAULTS["DEFAULT_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(job_id: str, scope_item_id: str, **overrides) -> dict:
    defaults = {"job_id": job_id, "scope_item_id": scope_item_id}
    defaults.update(overrides)
    return defaults


def create_financing_plan_payload(job_id: str, expected_job_version: int, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "principal_cents": 500_000,
        "term_months": 60,
        "apr_bps": 600,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults
