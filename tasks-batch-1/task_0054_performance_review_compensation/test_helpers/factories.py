"""Payload factories — one per entity, input fields only.

Field names are PRD-exact (Performance Review & Compensation Planning API).
"""

DEFAULT_HIRE_DATE = "2018-01-01T00:00:00.000Z"


def create_cycle_payload(**overrides) -> dict:
    """Inputs: name, cadence, merit_budget_pct, equity_refresh_pool,
    bell_curve_target, distribution_tolerance? (optional, defaults 0.05)."""
    defaults = {
        "name": "FY26 Annual",
        "cadence": "ANNUAL",
        "merit_budget_pct": 0.10,
        "equity_refresh_pool": 1000,
        "bell_curve_target": {"MEETS": 1.0},
    }
    defaults.update(overrides)
    return defaults


def create_rating_band_payload(**overrides) -> dict:
    """Inputs: label, min_score, max_score, merit_pct, pip_eligible? (default false)."""
    defaults = {
        "label": "MEETS",
        "min_score": 0,
        "max_score": 100,
        "merit_pct": 0.04,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    """Inputs: full_name, manager_id? , department, hire_date, is_active? (default true)."""
    defaults = {
        "full_name": "Test Employee",
        "department": "ENG",
        "hire_date": DEFAULT_HIRE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(cycle_id, employee_id, reviewer_id, **overrides) -> dict:
    """Inputs: cycle_id, employee_id, reviewer_id, base_salary."""
    defaults = {
        "cycle_id": cycle_id,
        "employee_id": employee_id,
        "reviewer_id": reviewer_id,
        "base_salary": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    """Inputs: title, weight, attainment_pct? (optional)."""
    defaults = {
        "title": "Ship the thing",
        "weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_feedback_request_payload(rater_id, **overrides) -> dict:
    """Inputs: rater_id, relationship."""
    defaults = {
        "rater_id": rater_id,
        "relationship": "PEER",
    }
    defaults.update(overrides)
    return defaults


def create_calibration_session_payload(cycle_id, facilitator_id, **overrides) -> dict:
    """Inputs: cycle_id, department, facilitator_id."""
    defaults = {
        "cycle_id": cycle_id,
        "department": "ENG",
        "facilitator_id": facilitator_id,
    }
    defaults.update(overrides)
    return defaults


def create_comp_plan_payload(cycle_id, review_id, expected_review_version, **overrides) -> dict:
    """Inputs: cycle_id, review_id, plan_type, promo_band_jump?, expected_review_version."""
    defaults = {
        "cycle_id": cycle_id,
        "review_id": review_id,
        "plan_type": "MERIT_ONLY",
        "expected_review_version": expected_review_version,
    }
    defaults.update(overrides)
    return defaults
