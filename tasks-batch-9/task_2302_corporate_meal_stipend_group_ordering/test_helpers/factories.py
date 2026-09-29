"""Payload factories — one per entity, input fields only."""

from .constants import (
    LUNCH_WINDOW_END_MINUTE,
    LUNCH_WINDOW_START_MINUTE,
    MONDAY_NOON,
    TEST_DEFAULTS,
    WEEKDAYS_MON_TO_FRI,
)


def order_line(item_name="Pad Thai", unit_price_cents=1000, quantity=1) -> dict:
    """One element of an order's `lines` array."""
    return {
        "item_name": item_name,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
    }


def create_meal_program_payload(**overrides) -> dict:
    """POST /meal-programs. Only employer_name, billing_account_ref and
    eligible_cuisines are required; the policy selectors are optional."""
    defaults = {
        "employer_name": TEST_DEFAULTS["EMPLOYER_NAME"],
        "billing_account_ref": TEST_DEFAULTS["BILLING_ACCOUNT_REF"],
        "eligible_cuisines": [TEST_DEFAULTS["CUISINE"]],
    }
    defaults.update(overrides)
    return defaults


def create_employee_group_payload(**overrides) -> dict:
    """POST /meal-programs/{id}/employee-groups."""
    defaults = {
        "name": "Engineering",
        "headcount_planned": TEST_DEFAULTS["HEADCOUNT_PLANNED"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_rule_payload(**overrides) -> dict:
    """POST /employee-groups/{id}/budget-rules."""
    defaults = {
        "effective_from": "2026-08-01T00:00:00Z",
        "per_meal_cap_cents": TEST_DEFAULTS["PER_MEAL_CAP_CENTS"],
        "daily_meal_limit": TEST_DEFAULTS["DAILY_MEAL_LIMIT"],
        "monthly_allocation_cents": TEST_DEFAULTS["MONTHLY_ALLOCATION_CENTS"],
        "eligible_weekdays": list(WEEKDAYS_MON_TO_FRI),
        "eligible_window_start_minute": LUNCH_WINDOW_START_MINUTE,
        "eligible_window_end_minute": LUNCH_WINDOW_END_MINUTE,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_location_payload(**overrides) -> dict:
    """POST /meal-programs/{id}/delivery-locations."""
    defaults = {
        "label": "HQ Lobby",
        "grid_x_km": 0.0,
        "grid_y_km": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_restaurant_payload(**overrides) -> dict:
    """POST /restaurants."""
    defaults = {
        "name": "Thai Garden",
        "cuisine": TEST_DEFAULTS["CUISINE"],
        "grid_x_km": 3.0,
        "grid_y_km": 4.0,
        "delivery_radius_km": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(program_id, group_id, **overrides) -> dict:
    """POST /employees."""
    defaults = {
        "program_id": program_id,
        "group_id": group_id,
        "full_name": "Ada Lovelace",
        "email": "ada@acme.test",
        "personal_card_on_file": True,
    }
    defaults.update(overrides)
    return defaults


def create_benefit_period_payload(employee_id, **overrides) -> dict:
    """POST /benefit-periods."""
    defaults = {
        "employee_id": employee_id,
        "period_month": TEST_DEFAULTS["PERIOD_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(
    employee_id, benefit_period_id, restaurant_id, delivery_location_id, **overrides
) -> dict:
    """POST /orders."""
    defaults = {
        "employee_id": employee_id,
        "benefit_period_id": benefit_period_id,
        "restaurant_id": restaurant_id,
        "delivery_location_id": delivery_location_id,
        "requested_delivery_at": MONDAY_NOON,
        "lines": [order_line()],
    }
    defaults.update(overrides)
    return defaults


def create_group_order_payload(
    program_id, organizer_employee_id, restaurant_id, delivery_location_id, **overrides
) -> dict:
    """POST /group-orders."""
    defaults = {
        "program_id": program_id,
        "organizer_employee_id": organizer_employee_id,
        "restaurant_id": restaurant_id,
        "delivery_location_id": delivery_location_id,
        "cutoff_at": "2026-08-03T11:30:00Z",
        "window_start": "2026-08-03T12:00:00Z",
        "window_end": "2026-08-03T12:30:00Z",
        "per_person_limit_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_credit_claim_payload(order_id, **overrides) -> dict:
    """POST /credit-claims."""
    defaults = {
        "order_id": order_id,
        "claim_type": "QUALITY_ISSUE",
        "claimed_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_expense_export_payload(**overrides) -> dict:
    """POST /meal-programs/{id}/expense-exports."""
    defaults = {
        "tax_month": TEST_DEFAULTS["PERIOD_MONTH"],
        "format": "CSV_EXPENSE_REPORT",
    }
    defaults.update(overrides)
    return defaults


def resolve_claim_payload(expected_order_version, **overrides) -> dict:
    """POST /credit-claims/{id}/resolve."""
    defaults = {
        "decision": "APPROVE",
        "expected_order_version": expected_order_version,
        "approved_cents": 1000,
        "routing_basis": "EMPLOYEE_FIRST",
    }
    defaults.update(overrides)
    return defaults
