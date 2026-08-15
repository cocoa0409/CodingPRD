"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import TEST_DEFAULTS


def create_housing_site_payload(**overrides) -> dict:
    defaults = {"name": "Harvest Site", "state_code": TEST_DEFAULTS["STATE_CODE"]}
    defaults.update(overrides)
    return defaults


def create_season_window_payload(site_id, expected_site_version, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "label": "2026 Harvest",
        "planned_open_date": TEST_DEFAULTS["WINDOW_OPEN"],
        "planned_close_date": TEST_DEFAULTS["WINDOW_CLOSE"],
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(site_id, **overrides) -> dict:
    defaults = {"site_id": site_id, "name": "B1"}
    defaults.update(overrides)
    return defaults


def create_housing_unit_payload(building_id, site_id, **overrides) -> dict:
    defaults = {
        "building_id": building_id,
        "site_id": site_id,
        "unit_code": "U1",
        "unit_type": TEST_DEFAULTS["UNIT_TYPE"],
        "max_occupancy": TEST_DEFAULTS["MAX_OCCUPANCY"],
        "monthly_rent_cents": TEST_DEFAULTS["MONTHLY_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_certification_payload(unit_id, **overrides) -> dict:
    defaults = {"unit_id": unit_id}
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "head_of_household_name": "Fam Test",
        "annual_family_income_cents": TEST_DEFAULTS["HOUSEHOLD_INCOME_CENTS"],
        "ag_work_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_household_member_payload(household_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "full_name": "Member One",
        "date_of_birth": "1990-01-01",
        "relationship": "HEAD",
    }
    defaults.update(overrides)
    return defaults


def create_deduction_authorization_payload(household_id, expected_household_version,
                                           **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "cap_percent": 0.25,
        "purpose": "RENT_AND_UTILITIES",
        "effective_date": "2026-08-01",
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults


def create_tenancy_payload(household_id, unit_id, expected_unit_version,
                           **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "unit_id": unit_id,
        "move_in_date": TEST_DEFAULTS["MOVE_IN_DATE"],
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_tenancy_payment_payload(**overrides) -> dict:
    defaults = {
        "gross_wages_cents": 100000,
        "pay_period_start": "2026-08-01",
        "pay_period_end": "2026-08-15",
    }
    defaults.update(overrides)
    return defaults


def create_charge_ledger_entry_payload(tenancy_id, **overrides) -> dict:
    defaults = {
        "tenancy_id": tenancy_id,
        "entry_type": "RENT",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "category": "OTHER",
        "severity": "MINOR",
        "description": "test work order",
    }
    defaults.update(overrides)
    return defaults


def create_pest_treatment_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "treatment_type": "ROUTINE",
        "scheduled_date": "2026-08-01",
        "reentry_buffer_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(tenancy_id, **overrides) -> dict:
    defaults = {
        "tenancy_id": tenancy_id,
        "category": "OTHER",
        "description": "test complaint",
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_inspection_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "agency": "STATE_HOUSING",
        "scheduled_date": "2026-08-15",
    }
    defaults.update(overrides)
    return defaults


def create_service_referral_payload(household_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "referral_type": "HEALTH",
        "agency_name": "Migrant Services",
    }
    defaults.update(overrides)
    return defaults
