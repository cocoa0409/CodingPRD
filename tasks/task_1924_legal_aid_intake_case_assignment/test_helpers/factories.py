"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Client",
        "residence_county": TEST_DEFAULTS["COUNTY"],
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
        "annual_gross_income_cents": TEST_DEFAULTS["GROSS_INCOME_CENTS"],
        "annual_countable_income_cents": TEST_DEFAULTS["COUNTABLE_INCOME_CENTS"],
        "receives_means_tested_benefits": False,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "case_type": "EVICTION_DEFENSE",
        "opposing_party_name": "Opposing Party",
        "incident_county": TEST_DEFAULTS["COUNTY"],
    }
    defaults.update(overrides)
    return defaults


def create_conflict_check_payload(**overrides) -> dict:
    defaults = {
        "result": "CLEAR",
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Staff Member",
        "staff_type": "ATTORNEY",
        "admitted_counties": [TEST_DEFAULTS["COUNTY"]],
        "practice_areas": ["EVICTION_DEFENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_panel_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Panel Member",
        "practice_areas": ["EVICTION_DEFENSE"],
        "counties": [TEST_DEFAULTS["COUNTY"]],
        "max_active_referrals": 3,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "panel_member_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_referral_accept_payload(**overrides) -> dict:
    defaults = {
        "decision": "ACCEPT",
        "service_start_date": "2026-09-01",
        "service_end_date": "2026-10-01",
    }
    defaults.update(overrides)
    return defaults


def create_grant_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Grant Program",
        "funder": "LSC",
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
        "allowed_case_types": ["CONSUMER_DEBT"],
        "allowed_counties": [TEST_DEFAULTS["COUNTY"]],
        "income_cap_percentage": 150.00,
        "per_case_rate_cents": 33_333,
        "total_budget_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_venue_rule_payload(**overrides) -> dict:
    defaults = {
        "county": TEST_DEFAULTS["COUNTY"],
        "case_type": "EVICTION_DEFENSE",
        "venue": "HOUSING_COURT",
        "priority_base_weight": 50,
        "extended_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(**overrides) -> dict:
    defaults = {
        "hours": 1.50,
        "activity_code": "RESEARCH",
        "work_date": "2026-08-05",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {
        "score": 5,
        "would_recommend": True,
    }
    defaults.update(overrides)
    return defaults
