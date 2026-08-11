"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "REGION_CODE": "R0",
    "REGION_NAME": "Region Zero",
    "MILEAGE_RATE_CENTS": 120,
    "TRAVEL_INCLUDED_MILES": 20,
    "SETUP_BUFFER_MINUTES": 30,
    "TEARDOWN_BUFFER_MINUTES": 30,
    "COMPANY_NAME": "ACME",
    "BILLING_EMAIL": "ap@acme.test",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "THERAPIST_NAME": "Therapist One",
    "THERAPIST_EMAIL": "t1@test",
    "PER_HOUR_RATE_CENTS": 6000,
    "MAX_MINUTES_PER_DAY": 480,
    "LICENSE_NUMBER": "LIC-1",
    "ISSUED_ON": "2025-01-01",
    "EXPIRES_ON": "2027-12-31",
    "SITE_ADDRESS": "1 Main St",
    "EVENT_DATE": "2026-06-10",
    "WINDOW_START_MINUTES": 600,
    "WINDOW_DURATION_MINUTES": 60,
    "CHAIR_COUNT": 1,
    "SLOT_MINUTES": 15,
    "PER_MINUTE_RATE_CENTS": 200,
    "PROGRAM_NAME": "Q3 Wellness",
    "PROGRAM_CADENCE": "WEEKLY",
    "WINDOW_START_TIME": "10:00",
    "RECURRENCE_DISCOUNT_PCT": 0.10,
    "SIGNATURE_PAYLOAD": "sig",
}


def create_region_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["REGION_CODE"],
        "name": DEFAULTS["REGION_NAME"],
        "base_mileage_rate_cents": DEFAULTS["MILEAGE_RATE_CENTS"],
        "travel_included_miles": DEFAULTS["TRAVEL_INCLUDED_MILES"],
        "setup_buffer_minutes": DEFAULTS["SETUP_BUFFER_MINUTES"],
        "teardown_buffer_minutes": DEFAULTS["TEARDOWN_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_corporate_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
        "region_id": None,
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_wellness_program_payload(**overrides) -> dict:
    defaults = {
        "corporate_account_id": None,
        "name": DEFAULTS["PROGRAM_NAME"],
        "cadence": DEFAULTS["PROGRAM_CADENCE"],
        "chair_count": DEFAULTS["CHAIR_COUNT"],
        "slot_minutes": DEFAULTS["SLOT_MINUTES"],
        "window_start_time": DEFAULTS["WINDOW_START_TIME"],
        "window_duration_minutes": DEFAULTS["WINDOW_DURATION_MINUTES"],
        "recurrence_discount_pct": DEFAULTS["RECURRENCE_DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_therapist_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["THERAPIST_NAME"],
        "email": DEFAULTS["THERAPIST_EMAIL"],
        "home_region_id": None,
        "per_hour_rate_cents": DEFAULTS["PER_HOUR_RATE_CENTS"],
        "max_minutes_per_day": DEFAULTS["MAX_MINUTES_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_therapist_license_payload(**overrides) -> dict:
    defaults = {
        "therapist_id": None,
        "region_id": None,
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "issued_on": DEFAULTS["ISSUED_ON"],
        "expires_on": DEFAULTS["EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "corporate_account_id": None,
        "region_id": None,
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "event_date": DEFAULTS["EVENT_DATE"],
        "window_start_minutes": DEFAULTS["WINDOW_START_MINUTES"],
        "window_duration_minutes": DEFAULTS["WINDOW_DURATION_MINUTES"],
        "chair_count": DEFAULTS["CHAIR_COUNT"],
        "slot_minutes": DEFAULTS["SLOT_MINUTES"],
        "per_minute_rate_cents": DEFAULTS["PER_MINUTE_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_claim_payload(**overrides) -> dict:
    defaults = {
        "recipient_name": "Recipient",
        "recipient_email": "r@x",
        "expected_chair_slot_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    defaults = {
        "booking_id": None,
        "signer_email": None,
        "signature_payload": DEFAULTS["SIGNATURE_PAYLOAD"],
    }
    defaults.update(overrides)
    return defaults


def create_satisfaction_survey_payload(**overrides) -> dict:
    defaults = {"rating": 5}
    defaults.update(overrides)
    return defaults
