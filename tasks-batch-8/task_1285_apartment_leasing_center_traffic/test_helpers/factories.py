"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_offer_counter = {"n": 0}


def create_property_payload(**overrides) -> dict:
    defaults = {"name": "Test Property", "code": "TP1"}
    defaults.update(overrides)
    return defaults


def create_agent_payload(property_id, **overrides) -> dict:
    defaults = {
        "full_name": "Test Agent",
        "email": "agent@example.com",
        "property_id": property_id,
    }
    defaults.update(overrides)
    return defaults


def create_floorplan_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "name": "A1 - 1BR/1BA",
        "bedrooms": 1,
        "base_rent_cents": TEST_DEFAULTS["BASE_RENT_CENTS"],
        "total_units": TEST_DEFAULTS["TOTAL_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_pricing_offer_payload(property_id, floorplan_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "floorplan_id": floorplan_id,
        "base_rent_cents": TEST_DEFAULTS["BASE_RENT_CENTS"],
        "effective_start": TEST_DEFAULTS["OFFER_WINDOW_START"],
        "expires_at": TEST_DEFAULTS["OFFER_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_inquiry_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "contact_name": "Prospect One",
        "contact_email": "prospect@example.com",
        "source": "WEB_FORM",
    }
    defaults.update(overrides)
    return defaults


def create_tour_payload(inquiry_id, **overrides) -> dict:
    defaults = {
        "inquiry_id": inquiry_id,
        "tour_type": "GUIDED",
        "scheduled_start": TEST_DEFAULTS["TOUR_START"],
        "scheduled_end": TEST_DEFAULTS["TOUR_END"],
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(floorplan_id, **overrides) -> dict:
    defaults = {
        "floorplan_id": floorplan_id,
        "contact_name": "Waitlist Prospect",
        "contact_email": "waitlist@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(floorplan_id, **overrides) -> dict:
    defaults = {
        "floorplan_id": floorplan_id,
        "applicant_name": "Applicant One",
        "applicant_email": "applicant@example.com",
        "annual_income_cents": TEST_DEFAULTS["ANNUAL_INCOME_CENTS"],
        "credit_score": TEST_DEFAULTS["CREDIT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(application_id, expected_application_version, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def create_move_in_payload(lease_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "scheduled_date": TEST_DEFAULTS["MOVE_IN_DATE"],
    }
    defaults.update(overrides)
    return defaults
