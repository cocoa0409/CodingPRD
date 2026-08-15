"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "STATE_CODE": "CA",
    "COVERAGE_LINE": "WC",
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2026-07-31T00:00:00Z",
    "ESTIMATED_ANNUAL_PREMIUM_CENTS": 600000,
    "MINIMUM_PREMIUM_CENTS": 10000,
    "PAYROLL_ESTIMATE_DOLLARS": 100000,
    "RATE_PER_100_CENTS": 40,
    "CC_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "CC_EFFECTIVE_TO": "2026-12-31T23:59:59Z",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-06-30T00:00:00Z",
    "APPT_START": "2026-08-10T09:00:00Z",
    "APPT_END": "2026-08-10T11:00:00Z",
}


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_number": "WC-FACTORY-1",
        "insured_name": "Factory Insured",
        "coverage_line": DEFAULTS["COVERAGE_LINE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
        "estimated_annual_premium_cents": DEFAULTS["ESTIMATED_ANNUAL_PREMIUM_CENTS"],
        "minimum_premium_cents": DEFAULTS["MINIMUM_PREMIUM_CENTS"],
        "payroll_estimate_dollars": DEFAULTS["PAYROLL_ESTIMATE_DOLLARS"],
        "class_code_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_auditor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ada Auditor",
        "territory_states": [DEFAULTS["STATE_CODE"]],
        "level": "SENIOR",
    }
    defaults.update(overrides)
    return defaults


def create_classification_code_payload(**overrides) -> dict:
    defaults = {
        "code": "8810",
        "description": "Clerical",
        "state_code": DEFAULTS["STATE_CODE"],
        "coverage_line": DEFAULTS["COVERAGE_LINE"],
        "rate_per_100_cents": DEFAULTS["RATE_PER_100_CENTS"],
        "high_hazard": False,
        "effective_from": DEFAULTS["CC_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["CC_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_records_request_payload(**overrides) -> dict:
    defaults = {"request_type": "PAYROLL_SUMMARY"}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": DEFAULTS["APPT_START"],
        "scheduled_end": DEFAULTS["APPT_END"],
        "location_type": "INSURED_PREMISES",
        "expected_work_order_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_allocation_payload(**overrides) -> dict:
    defaults = {
        "class_code_id": "",
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "gross_payroll_dollars": 40000,
        "expected_work_order_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_exposure_payload(**overrides) -> dict:
    defaults = {
        "subcontractor_name": "SubCo",
        "payments_dollars": 10000,
        "governing_class_code_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "insurer_name": "Zenith",
        "wc_coverage_present": True,
        "gl_coverage_present": False,
        "coverage_effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "coverage_expiration_date": DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"grounds": "PAYROLL_ERROR"}
    defaults.update(overrides)
    return defaults


def record_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 0}
    defaults.update(overrides)
    return defaults
