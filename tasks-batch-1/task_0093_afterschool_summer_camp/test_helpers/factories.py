"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides for the fields a
test needs to control. Optional fields (those with a PRD default) are omitted unless
overridden, so tests can exercise default behavior.
"""
from .constants import TEST_DEFAULTS


def create_guardian_payload(**overrides) -> dict:
    defaults = {
        "email": "guardian@example.com",
        "full_name": "Test Guardian",
        "phone": "555-0100",
        "home_zip": TEST_DEFAULTS["DEFAULT_HOME_ZIP"],
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(guardian_id: str, **overrides) -> dict:
    # household_size is optional (defaults to 1 server-side); omit unless overridden.
    defaults = {
        "guardian_id": guardian_id,
        "first_name": "Test Child",
        "birth_date": TEST_DEFAULTS["DEFAULT_BIRTH_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_emergency_contact_payload(child_id: str, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "contact_name": "Emergency Person",
        "contact_phone": "555-0199",
        "relationship": "grandparent",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_form_payload(child_id: str, form_type: str, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "form_type": form_type,
    }
    if form_type == "MEDICAL":
        defaults["medication_notes"] = "none"
    elif form_type == "PICKUP":
        defaults["authorized_pickup_names"] = ["Test Guardian"]
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Program",
        "program_type": "CAMP",
        "min_age": 5,
        "max_age": 12,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "title": "Test Session",
        "age_group_min": 8,
        "age_group_max": 12,
        "age_as_of_date": TEST_DEFAULTS["DEFAULT_AGE_AS_OF_DATE"],
        "weekly_capacity": 5,
        "base_weekly_tuition_cents": TEST_DEFAULTS["CAMP_BASE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_weekly_offering_payload(session_id: str, **overrides) -> dict:
    # rain_alternate_offering_id is optional; omit unless overridden.
    defaults = {
        "session_id": session_id,
        "week_start": TEST_DEFAULTS["DEFAULT_WEEK_START"],
    }
    defaults.update(overrides)
    return defaults


def create_scholarship_award_payload(child_id: str, tier: str, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(child_id: str, weekly_offering_id: str,
                              expected_weekly_offering_version: int, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "weekly_offering_id": weekly_offering_id,
        "expected_weekly_offering_version": expected_weekly_offering_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(invoice_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(weekly_offering_id: str, **overrides) -> dict:
    defaults = {
        "weekly_offering_id": weekly_offering_id,
    }
    defaults.update(overrides)
    return defaults


def finalize_invoice_payload(expected_invoice_version: int, **overrides) -> dict:
    defaults = {
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


def configure_rain_alternate_payload(rain_alternate_offering_id: str,
                                     expected_weekly_offering_version: int, **overrides) -> dict:
    defaults = {
        "rain_alternate_offering_id": rain_alternate_offering_id,
        "expected_weekly_offering_version": expected_weekly_offering_version,
    }
    defaults.update(overrides)
    return defaults
