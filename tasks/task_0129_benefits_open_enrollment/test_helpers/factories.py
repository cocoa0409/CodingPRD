"""Payload factories — one per entity, input fields only (PRD Section 3)."""


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Employee",
        "hire_date": "2026-01-01",
        "employment_type": "FULL_TIME",
        "payroll_schedule": "SEMI_MONTHLY",
        "monthly_household_income_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_waiting_period_payload(**overrides) -> dict:
    defaults = {
        "window_type": "INITIAL",
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_plan_offering_payload(**overrides) -> dict:
    defaults = {
        "benefit_type": "MEDICAL",
        "name": "Gold PPO",
    }
    defaults.update(overrides)
    return defaults


def create_plan_tier_payload(**overrides) -> dict:
    defaults = {
        "plan_offering_id": None,
        "coverage_level": "EMPLOYEE_ONLY",
        "monthly_premium_cents": 60000,
        "employer_contribution_pct": 0.70,
    }
    defaults.update(overrides)
    return defaults


def create_dependent_payload(**overrides) -> dict:
    defaults = {
        "relationship": "CHILD",
        "full_name": "Test Dependent",
        "date_of_birth": "2020-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {
        "plan_tier_id": None,
        "coverage_start_date": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_life_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "MARRIAGE",
        "event_date": "2026-02-01",
        "requested_plan_tier_id": None,
        "adjustment_mode": "PROSPECTIVE",
    }
    defaults.update(overrides)
    return defaults


def generate_form_1095c_payload(**overrides) -> dict:
    defaults = {"tax_year": 2026}
    defaults.update(overrides)
    return defaults
