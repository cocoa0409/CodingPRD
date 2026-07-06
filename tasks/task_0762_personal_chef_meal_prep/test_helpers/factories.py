"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def ingredient(name, quantity, unit, unit_cost_cents, allergen_tags=None) -> dict:
    """Build one ingredient object for a meal's ingredients array."""
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "unit_cost_cents": unit_cost_cents,
        "allergen_tags": list(allergen_tags or []),
    }


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Client",
        "email": _unique_email("client"),
        "household_size": 2,
        "billing_mode": "PER_WEEK",
        "weekly_base_fee_cents": TEST_DEFAULTS["WEEKLY_BASE_FEE_CENTS"],
        "per_meal_fee_cents": TEST_DEFAULTS["PER_MEAL_FEE_CENTS"],
        "weekly_grocery_budget_cents": TEST_DEFAULTS["WEEKLY_GROCERY_BUDGET_CENTS"],
        "kitchen_open_hour": 0,
        "kitchen_close_hour": 24,
    }
    defaults.update(overrides)
    return defaults


def create_chef_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Chef",
        "email": _unique_email("chef"),
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dietary_plan_payload(client_id, expected_client_version, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "restriction_tags": ["OMNIVORE"],
        "allergen_tags": [],
        "daily_calorie_target": 2000,
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_weekly_menu_payload(client_id, dietary_plan_id, chef_id,
                               week_start_date=None, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "dietary_plan_id": dietary_plan_id,
        "chef_id": chef_id,
        "week_start_date": week_start_date or TEST_DEFAULTS["WEEK_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_meal_payload(weekly_menu_id, meal_name="Test Meal", meal_slot="DINNER",
                             servings=2, ingredients=None, **overrides) -> dict:
    defaults = {
        "weekly_menu_id": weekly_menu_id,
        "meal_name": meal_name,
        "meal_slot": meal_slot,
        "servings": servings,
        "ingredients": ingredients if ingredients is not None else [
            ingredient("rice", 1, "batch", 4000)
        ],
    }
    defaults.update(overrides)
    return defaults


def create_cook_session_payload(weekly_menu_id, chef_id, scheduled_start,
                                scheduled_end, **overrides) -> dict:
    defaults = {
        "weekly_menu_id": weekly_menu_id,
        "chef_id": chef_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def substitute_payload(target_ingredient_name, replacement_name, replacement_quantity,
                       replacement_unit, replacement_unit_cost_cents,
                       replacement_allergen_tags=None) -> dict:
    return {
        "target_ingredient_name": target_ingredient_name,
        "replacement_name": replacement_name,
        "replacement_quantity": replacement_quantity,
        "replacement_unit": replacement_unit,
        "replacement_unit_cost_cents": replacement_unit_cost_cents,
        "replacement_allergen_tags": list(replacement_allergen_tags or []),
    }


def feedback_payload(rating, comment=None) -> dict:
    payload = {"rating": rating}
    if comment is not None:
        payload["comment"] = comment
    return payload
