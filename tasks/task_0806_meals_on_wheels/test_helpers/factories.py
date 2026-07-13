"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CLIENT_NAME": "Ada Client",
    "BIRTH_DATE": "1950-06-15",
    "HOUSEHOLD_SIZE": 1,
    "MONTHLY_INCOME_CENTS": 120000,
    "ADDRESS_ZONE": "Z1",
    "PHONE": "555-0101",
    "DRIVER_NAME": "Dana Driver",
    "DRIVER_PHONE": "555-0100",
    "ROUTE_NAME": "R1",
    "ZONE": "Z1",
    "SERVICE_DAYS": ["MON", "WED", "FRI"],
    "MAX_MEALS_PER_RUN": 50,
    "NUTRITION_POINTS": 1,
    "ADL_SCORE": 0,
    "RECOMMENDED_MEALS_PER_DAY": 2,
    "MEAL_TYPE": "HOT",
    "MEALS_PER_DAY": 2,
    "DELIVERY_DAYS": ["MON", "WED", "FRI"],
    "AMOUNT_CENTS": 5000,
    "PERIOD_MONTH": "2026-03",
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "monthly_income_cents": DEFAULTS["MONTHLY_INCOME_CENTS"],
        "address_zone": DEFAULTS["ADDRESS_ZONE"],
        "phone": DEFAULTS["PHONE"],
    }
    payload.update(overrides)
    return payload


def update_client_payload(expected_client_version, **overrides) -> dict:
    """PATCH body: expected_client_version is required; other fields optional."""
    payload = {"expected_client_version": expected_client_version}
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["DRIVER_NAME"],
        "phone": DEFAULTS["DRIVER_PHONE"],
    }
    payload.update(overrides)
    return payload


def create_route_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROUTE_NAME"],
        "zone": DEFAULTS["ZONE"],
        "service_days": list(DEFAULTS["SERVICE_DAYS"]),
        "max_meals_per_run": DEFAULTS["MAX_MEALS_PER_RUN"],
    }
    payload.update(overrides)
    return payload


def assign_driver_payload(driver_id, **overrides) -> dict:
    payload = {"driver_id": driver_id}
    payload.update(overrides)
    return payload


def create_assessment_payload(**overrides) -> dict:
    """Input fields for POST /clients/{id}/assessments (client_id comes from path).
    therapeutic_diet_required / therapeutic_diet_type are optional (defaults false/NONE)."""
    payload = {
        "nutrition_determine_points": DEFAULTS["NUTRITION_POINTS"],
        "adl_score": DEFAULTS["ADL_SCORE"],
        "recommended_meals_per_day": DEFAULTS["RECOMMENDED_MEALS_PER_DAY"],
    }
    payload.update(overrides)
    return payload


def create_meal_plan_payload(assessment_id, route_id, expected_client_version, **overrides) -> dict:
    payload = {
        "assessment_id": assessment_id,
        "route_id": route_id,
        "meal_type": DEFAULTS["MEAL_TYPE"],
        "meals_per_day": DEFAULTS["MEALS_PER_DAY"],
        "delivery_days": list(DEFAULTS["DELIVERY_DAYS"]),
        "expected_client_version": expected_client_version,
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(meal_plan_id, scheduled_date, **overrides) -> dict:
    payload = {
        "meal_plan_id": meal_plan_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def complete_delivery_payload(outcome, **overrides) -> dict:
    """Body for POST /deliveries/{id}/complete. wellness_notes optional."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_contribution_payload(**overrides) -> dict:
    payload = {
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "period_month": DEFAULTS["PERIOD_MONTH"],
    }
    payload.update(overrides)
    return payload


def create_vacation_hold_payload(start_date, end_date, **overrides) -> dict:
    payload = {"start_date": start_date, "end_date": end_date}
    payload.update(overrides)
    return payload
