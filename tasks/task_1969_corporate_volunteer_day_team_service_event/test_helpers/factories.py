"""Payload factories — one per entity, input fields only."""
from .constants import ADULT_DOB, EVENT_END, EVENT_START

DEFAULTS = {
    "PARTNER_NAME": "River Guild",
    "PARTNER_EMAIL": "ops@river.org",
    "EVENT_NAME": "Volunteer Day",
    "BUDGET_CENTS": 1_000_000,
    "PROJECT_TITLE": "Trail Repair",
    "MIN_VOLUNTEERS": 1,
    "MAX_VOLUNTEERS": 10,
    "VENDOR_NAME": "FreshCo",
    "PER_PERSON_COST_CENTS": 1000,
    "VEHICLE_NAME": "Bus-7",
    "SEAT_CAPACITY": 40,
    "SPONSOR_NAME": "CorpCo",
}


def create_nonprofit_partner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PARTNER_NAME"],
        "contact_email": DEFAULTS["PARTNER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_service_event_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["EVENT_NAME"],
        "event_start_at": EVENT_START,
        "event_end_at": EVENT_END,
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_service_project_payload(**overrides) -> dict:
    defaults = {
        "nonprofit_id": "placeholder",
        "title": DEFAULTS["PROJECT_TITLE"],
        "min_volunteers": DEFAULTS["MIN_VOLUNTEERS"],
        "max_volunteers": DEFAULTS["MAX_VOLUNTEERS"],
    }
    defaults.update(overrides)
    return defaults


def create_employee_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Vol One",
        "email": "v1@corp.com",
        "department": "Eng",
        "date_of_birth": ADULT_DOB,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "event_id": "placeholder",
        "project_id": "placeholder",
    }
    defaults.update(overrides)
    return defaults


def create_sign_waiver_payload(**overrides) -> dict:
    defaults = {
        "signer_name": "Vol One",
        "signer_relation": "SELF",
        "media_consent": False,
    }
    defaults.update(overrides)
    return defaults


def create_procurement_order_payload(**overrides) -> dict:
    defaults = {
        "event_id": "placeholder",
        "project_id": "placeholder",
        "lines": [{"item_name": "Gloves", "quantity": 2, "unit_cost_cents": 500}],
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VEHICLE_NAME"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_transport_manifest_payload(**overrides) -> dict:
    defaults = {
        "event_id": "placeholder",
        "vehicle_id": "placeholder",
        "depart_at": "2026-08-20T08:00:00Z",
        "return_at": "2026-08-20T10:00:00Z",
        "cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_meal_plan_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "per_person_cost_cents": DEFAULTS["PER_PERSON_COST_CENTS"],
        "expected_event_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_supervision_assignment_payload(**overrides) -> dict:
    defaults = {
        "project_id": "placeholder",
        "lead_volunteer_id": "placeholder",
    }
    defaults.update(overrides)
    return defaults


def create_sponsorship_payload(**overrides) -> dict:
    defaults = {
        "event_id": "placeholder",
        "sponsor_name": DEFAULTS["SPONSOR_NAME"],
        "match_type": "FLAT",
        "rate_cents": 5000,
        "pledge_cap_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_impact_record_payload(**overrides) -> dict:
    defaults = {
        "registration_id": "placeholder",
        "project_id": "placeholder",
        "hours_attended": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_feedback_survey_payload(**overrides) -> dict:
    defaults = {
        "registration_id": "placeholder",
        "rating": 5,
        "would_repeat": True,
    }
    defaults.update(overrides)
    return defaults
