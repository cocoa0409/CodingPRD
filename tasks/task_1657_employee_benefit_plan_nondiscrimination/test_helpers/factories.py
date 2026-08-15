"""Payload factories — one per entity, input fields only (PRD §3)."""

_SSN_COUNTER = {"value": 100000000}


def next_ssn() -> str:
    """Deterministic unique 9-digit SSN per call within a test process."""
    _SSN_COUNTER["value"] += 1
    return str(_SSN_COUNTER["value"])


_EIN_COUNTER = {"value": 100000000}


def next_ein() -> str:
    _EIN_COUNTER["value"] += 1
    return str(_EIN_COUNTER["value"])


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer Corp",
        "ein": next_ein(),
        "entity_type": "CORPORATION",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Test 401k Plan",
        "plan_type": "401K",
        "plan_number": "001",
    }
    defaults.update(overrides)
    return defaults


def create_plan_version_payload(**overrides) -> dict:
    defaults = {
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
        "comp_definition": "W2",
        "safe_harbor_design": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_plan_year_payload(**overrides) -> dict:
    defaults = {
        "year_label": 2026,
        "year_start": "2026-01-01",
        "year_end": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_census_employee_payload(**overrides) -> dict:
    defaults = {
        "ssn": next_ssn(),
        "full_name": "Test Employee",
        "date_of_birth": "1980-01-01",
        "date_of_hire": "2020-01-01",
        "employment_status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_compensation_record_payload(**overrides) -> dict:
    defaults = {
        "comp_source": "W2",
        "amount_cents": 10000000,
        "period": "CURRENT_YEAR",
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(**overrides) -> dict:
    defaults = {
        "contribution_type": "ELECTIVE_DEFERRAL",
        "amount_cents": 100000,
        "contribution_date": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_limit_payload(**overrides) -> dict:
    defaults = {
        "year_label": 2026,
        "hce_comp_threshold_cents": 15500000,
        "key_officer_comp_threshold_cents": 22000000,
        "sec402g_limit_cents": 2350000,
        "sec415_annual_additions_limit_cents": 6900000,
        "dependent_care_limit_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_test_run_payload(**overrides) -> dict:
    defaults = {
        "test_scope": "ADP_401K",
        "run_mode": "FINAL",
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(**overrides) -> dict:
    defaults = {
        "correction_type": "CORRECTIVE_DISTRIBUTION",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_safe_harbor_election_payload(**overrides) -> dict:
    defaults = {
        "design": "BASIC_MATCH",
        "elected_on": "2025-10-15",
    }
    defaults.update(overrides)
    return defaults


def create_safe_harbor_notice_payload(**overrides) -> dict:
    defaults = {
        "notice_period_start": "2025-11-01",
        "notice_period_end": "2025-11-30",
    }
    defaults.update(overrides)
    return defaults
