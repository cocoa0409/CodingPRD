"""Payload factories — one per entity, input fields only (Food Safety Inspection API)."""
from .constants import TEST_DEFAULTS


def create_fda_food_code_payload(**overrides) -> dict:
    """Input fields for POST /fda-food-codes.

    repeat_surcharge_points is optional (defaults to 0 server-side) so it is
    only included when explicitly supplied via overrides.
    """
    defaults = {
        "code": "3-501.16",
        "title": "Cold holding",
        "classification": "CRITICAL",
        "base_demerit_points": 10,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    """Input fields for POST /inspectors.

    max_daily_route_stops is optional (defaults to 8 server-side).
    """
    defaults = {
        "full_name": TEST_DEFAULTS["INSPECTOR_NAME"],
        "badge_number": TEST_DEFAULTS["BADGE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_establishment_payload(**overrides) -> dict:
    """Input fields for POST /establishments.

    cuisine_type, serves_raw_animal_foods, does_onsite_processing are optional.
    """
    defaults = {
        "name": TEST_DEFAULTS["ESTABLISHMENT_NAME"],
        "address": TEST_DEFAULTS["ESTABLISHMENT_ADDRESS"],
        "seating_capacity": TEST_DEFAULTS["SEATING_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_review_payload(establishment_id: str, **overrides) -> dict:
    """Input fields for POST /plan-reviews."""
    defaults = {
        "establishment_id": establishment_id,
        "submitted_layout_sqft": TEST_DEFAULTS["PLAN_SQFT"],
        "equipment_count": TEST_DEFAULTS["PLAN_EQUIP"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(establishment_id: str, plan_review_id: str, **overrides) -> dict:
    """Input fields for POST /permits."""
    defaults = {
        "establishment_id": establishment_id,
        "plan_review_id": plan_review_id,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_route_payload(inspector_id: str, route_date_index: int, **overrides) -> dict:
    """Input fields for POST /inspection-routes."""
    defaults = {
        "inspector_id": inspector_id,
        "route_date_index": route_date_index,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(establishment_id: str, inspector_id: str,
                              inspection_type: str, scheduled_index: int, **overrides) -> dict:
    """Input fields for POST /inspections.

    route_id and reinspection_of_id are optional.
    """
    defaults = {
        "establishment_id": establishment_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_index": scheduled_index,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(inspection_id: str, fda_code_id: str, **overrides) -> dict:
    """Input fields for POST /violations.

    corrected_on_site is optional (defaults to false server-side).
    """
    defaults = {
        "inspection_id": inspection_id,
        "fda_code_id": fda_code_id,
    }
    defaults.update(overrides)
    return defaults


def create_closure_order_payload(establishment_id: str, triggering_inspection_id: str,
                                 reason_code: str, **overrides) -> dict:
    """Input fields for POST /closure-orders."""
    defaults = {
        "establishment_id": establishment_id,
        "triggering_inspection_id": triggering_inspection_id,
        "reason_code": reason_code,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(establishment_id: str, complaint_type: str, **overrides) -> dict:
    """Input fields for POST /complaints.

    reported_ill_count is optional (defaults to 0 server-side).
    """
    defaults = {
        "establishment_id": establishment_id,
        "complaint_type": complaint_type,
    }
    defaults.update(overrides)
    return defaults


def create_enforcement_case_payload(establishment_id: str, alleged_penalty_cents: int,
                                    **overrides) -> dict:
    """Input fields for POST /enforcement-cases.

    closure_order_id is optional (null for fine-only cases).
    """
    defaults = {
        "establishment_id": establishment_id,
        "alleged_penalty_cents": alleged_penalty_cents,
    }
    defaults.update(overrides)
    return defaults
