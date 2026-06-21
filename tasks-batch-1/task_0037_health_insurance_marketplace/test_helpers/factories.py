"""Payload factories — one per entity, input fields only."""


def create_household_payload(**overrides) -> dict:
    defaults = {
        "coverage_year": 2026,
        "rating_area": "RA01",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "relationship": "PRIMARY",
        "tax_filing_status": "FILER",
        "annual_income_cents": 3_000_000,
        "applies_for_coverage": True,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(household_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "enrollment_window": "OEP",
    }
    defaults.update(overrides)
    return defaults


def create_health_plan_payload(**overrides) -> dict:
    defaults = {
        "rating_area": "RA01",
        "coverage_year": 2026,
        "metal_tier": "SILVER",
        "gross_premium_cents": 50_000,
        "is_slcsp_benchmark": True,
    }
    defaults.update(overrides)
    return defaults


def create_sep_request_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "qualifying_event_type": "BIRTH",
        "event_date": "2026-06-16",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(application_id, plan_id, expected_household_version, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "plan_id": plan_id,
        "elected_aptc_monthly_cents": 0,
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(enrollment_id, actual_annual_magi_cents, months_enrolled, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "actual_annual_magi_cents": actual_annual_magi_cents,
        "months_enrolled": months_enrolled,
    }
    defaults.update(overrides)
    return defaults
