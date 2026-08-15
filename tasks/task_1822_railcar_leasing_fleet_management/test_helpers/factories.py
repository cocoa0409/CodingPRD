"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

DEFAULTS = {
    "COMPANY_NAME": "Test Lessee Co",
    "CREDIT_TIER": "TIER_A",
    "CREDIT_LIMIT_CENTS": 100000000,
    "SECURITY_DEPOSIT_CENTS": 0,
    "CAR_TYPE": "COVERED_HOPPER",
    "BUILT_YEAR": 2015,
    "HIRE_RATE_CENTS": 9000,
    "MILEAGE_RATE_CENTS": 55,
    "TARIFF_FROM": "2026-01-01",
    "TARIFF_TO": "2027-01-01",
    "LEASE_TYPE": "FULL_SERVICE",
    "BASE_DAILY_RATE_CENTS": 5000,
    "LESSOR_SHARE_PCT": 100,
    "REPAIR_CAP_CENTS": 20000,
    "LEASE_START": "2026-08-01",
    "LEASE_END": "2027-07-31",
    "COMMODITY": "GRAIN",
    "WINDOW_START": "2026-08-01",
    "WINDOW_END": "2026-12-31",
}


def create_lessee_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "credit_tier": DEFAULTS["CREDIT_TIER"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "security_deposit_cents": DEFAULTS["SECURITY_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_railcar_payload(**overrides) -> dict:
    defaults = {
        "car_mark": "GATX1001",
        "car_type": DEFAULTS["CAR_TYPE"],
        "built_year": DEFAULTS["BUILT_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_rate_payload(**overrides) -> dict:
    defaults = {
        "car_type": DEFAULTS["CAR_TYPE"],
        "rate_kind": "CAR_HIRE_BASE",
        "effective_from": DEFAULTS["TARIFF_FROM"],
        "effective_to": DEFAULTS["TARIFF_TO"],
        "unit_rate_cents": DEFAULTS["HIRE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_agreement_payload(**overrides) -> dict:
    defaults = {
        "lessee_id": None,
        "lease_type": DEFAULTS["LEASE_TYPE"],
        "base_daily_rate_cents": DEFAULTS["BASE_DAILY_RATE_CENTS"],
        "car_hire_lessor_share_pct": DEFAULTS["LESSOR_SHARE_PCT"],
        "authorized_repair_cap_cents": DEFAULTS["REPAIR_CAP_CENTS"],
        "start_date": DEFAULTS["LEASE_START"],
        "end_date": DEFAULTS["LEASE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_assignment_payload(**overrides) -> dict:
    defaults = {
        "lease_id": None,
        "railcar_id": None,
        "planned_commodity": DEFAULTS["COMMODITY"],
        "scheduled_start": DEFAULTS["WINDOW_START"],
        "scheduled_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_mileage_report_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "lease_assignment_id": None,
        "report_month": "2026-08",
        "loaded_miles": 1000,
        "empty_miles": 200,
    }
    defaults.update(overrides)
    return defaults


def create_repair_authorization_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "defect_description": "defect",
        "defect_cause": "WEAR_AND_TEAR",
        "estimate_cents": 100000,
        "requires_shop": False,
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_record_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "prior_commodity": "GRAIN",
        "next_commodity": "COAL",
        "planned_date": "2026-08-16",
    }
    defaults.update(overrides)
    return defaults


def damage_line_item(**overrides) -> dict:
    defaults = {
        "component": "WHEEL_SET",
        "severity": "MINOR",
        "cause": "LESSEE_DAMAGE",
        "parts_cents": 10000,
        "labor_hours": 0.5,
        "replaced": False,
    }
    defaults.update(overrides)
    return defaults


def create_damage_assessment_payload(**overrides) -> dict:
    defaults = {
        "lease_assignment_id": None,
        "railcar_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_directive_payload(**overrides) -> dict:
    defaults = {
        "directive_code": "DOT-117R",
        "description": "Tank car retrofit",
        "applies_to_car_types": ["TANK_GENERAL"],
        "retrofit_deadline": "2026-12-31",
        "grace_days": 30,
        "daily_penalty_cents": 25000,
        "penalty_cap_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_retrofit_order_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "directive_id": None,
        "scheduled_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults


def create_retirement_case_payload(**overrides) -> dict:
    defaults = {
        "railcar_id": None,
        "reason": "AGE_LIMIT",
    }
    defaults.update(overrides)
    return defaults


def create_capital_pool_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": 2026,
        "opening_balance_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(**overrides) -> dict:
    defaults = {
        "car_type": "COVERED_HOPPER",
        "unit_cost_cents": 10000000,
        "expected_pool_version": None,
    }
    defaults.update(overrides)
    return defaults
