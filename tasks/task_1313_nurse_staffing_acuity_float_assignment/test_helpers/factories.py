"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "UNIT_NAME": "4 West ICU",
    "UNIT_TYPE": "ICU",
    "BED_COUNT": 12,
    "INCENTIVE_BUDGET_CENTS": 500000,
    "NURSE_NAME": "Test Nurse",
    "EMPLOYMENT_TYPE": "CORE",
    "BASE_HOURLY_RATE_CENTS": 5000,
    "PATIENTS_PER_NURSE": 4,
    "SHIFT_DATE": "2026-08-10",
    "SHIFT_CODE": "DAY",
    "PATIENT_REF": "P-0001",
    "SITTER_START": "2026-08-10T09:00:00Z",
    "SITTER_END": "2026-08-10T13:00:00Z",
    "PREMIUM_MULTIPLIER": 1.5,
    "REPORT_DATE": "2026-08-10",
    "ACTUAL_HOURS_WORKED": 12.0,
    "MISSED_BREAKS": 0,
}


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["UNIT_NAME"],
        "unit_type": DEFAULTS["UNIT_TYPE"],
        "bed_count": DEFAULTS["BED_COUNT"],
        "incentive_budget_cents": DEFAULTS["INCENTIVE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_nurse_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["NURSE_NAME"],
        "employment_type": DEFAULTS["EMPLOYMENT_TYPE"],
        "competencies": ["ICU"],
        "base_hourly_rate_cents": DEFAULTS["BASE_HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_matrix_rule_payload(**overrides) -> dict:
    defaults = {
        "unit_type": DEFAULTS["UNIT_TYPE"],
        "acuity_level": "LOW",
        "patients_per_nurse": DEFAULTS["PATIENTS_PER_NURSE"],
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "shift_code": DEFAULTS["SHIFT_CODE"],
        "census_low": 4,
        "census_moderate": 0,
        "census_high": 0,
        "census_critical": 0,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": DEFAULTS["SHIFT_DATE"],
        "shift_code": DEFAULTS["SHIFT_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_float_request_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "premium_multiplier": DEFAULTS["PREMIUM_MULTIPLIER"],
    }
    defaults.update(overrides)
    return defaults


def create_sitter_request_payload(**overrides) -> dict:
    defaults = {
        "patient_ref": DEFAULTS["PATIENT_REF"],
        "start_at": DEFAULTS["SITTER_START"],
        "end_at": DEFAULTS["SITTER_END"],
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": DEFAULTS["REPORT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_completion_payload(**overrides) -> dict:
    defaults = {
        "actual_hours_worked": DEFAULTS["ACTUAL_HOURS_WORKED"],
        "missed_breaks": DEFAULTS["MISSED_BREAKS"],
    }
    defaults.update(overrides)
    return defaults
