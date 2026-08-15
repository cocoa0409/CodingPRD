"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Show",
        "event_date": TEST_DEFAULTS["EVENT_DATE"],
        "gates_open_at": TEST_DEFAULTS["GATES_OPEN_AT"],
        "judging_start_at": TEST_DEFAULTS["JUDGING_START_AT"],
        "judging_end_at": TEST_DEFAULTS["JUDGING_END_AT"],
        "ballot_close_at": TEST_DEFAULTS["BALLOT_CLOSE_AT"],
        "prereg_deadline": TEST_DEFAULTS["PREREG_DEADLINE"],
        "curfew_start": TEST_DEFAULTS["CURFEW_START"],
        "curfew_end": TEST_DEFAULTS["CURFEW_END"],
        "liability_policy_number": "POL-1",
    }
    defaults.update(overrides)
    return defaults


def create_class_payload(**overrides) -> dict:
    defaults = {
        "code": "OPEN",
        "name": "Open Class",
        "min_year": 1900,
        "max_year": 2026,
        "prereg_fee_cents": TEST_DEFAULTS["PREREG_FEE_CENTS"],
        "day_of_fee_cents": TEST_DEFAULTS["DAY_OF_FEE_CENTS"],
        "capacity": 40,
        "judging_mode": "PEOPLES_CHOICE",
        "award_depth": 1,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "name": "Show Field A",
        "zone_type": "SHOW_FIELD",
        "capacity": 50,
    }
    defaults.update(overrides)
    return defaults


def create_registrant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Entrant",
        "email": "entrant@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "year": 1970,
        "make": "Ford",
        "model": "Mustang",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(event_id, registrant_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "registrant_id": registrant_id,
        "signature_name": "Test Entrant",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(event_id, registrant_id, vehicle_id, class_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "registrant_id": registrant_id,
        "vehicle_id": vehicle_id,
        "class_id": class_id,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": TEST_DEFAULTS["PREREG_FEE_CENTS"],
        "method": "CASH",
    }
    defaults.update(overrides)
    return defaults


def create_judge_payload(**overrides) -> dict:
    defaults = {
        "name": "Judge One",
        "email": "judge@example.com",
        "assigned_class_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_criteria_scores(exterior=8, interior=8, engine=8, authenticity=8, condition=8) -> list:
    return [
        {"criterion": "EXTERIOR", "points": exterior},
        {"criterion": "INTERIOR", "points": interior},
        {"criterion": "ENGINE", "points": engine},
        {"criterion": "AUTHENTICITY", "points": authenticity},
        {"criterion": "CONDITION", "points": condition},
    ]


def create_score_sheet_payload(registration_id, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "criteria_scores": create_criteria_scores(),
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(event_id, registration_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "registration_id": registration_id,
    }
    defaults.update(overrides)
    return defaults


def create_booth_application_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "business_name": "Test Vendor",
        "contact_email": "vendor@example.com",
        "booth_tier": "SINGLE",
    }
    defaults.update(overrides)
    return defaults


def create_sound_slot_payload(**overrides) -> dict:
    defaults = {
        "performer_name": "House Band",
        "slot_start": "2026-08-15T19:00:00Z",
        "slot_end": "2026-08-15T20:00:00Z",
        "expected_db": 90.0,
    }
    defaults.update(overrides)
    return defaults


def create_noise_reading_payload(**overrides) -> dict:
    defaults = {
        "reading_db": 96.0,
        "source": "STAGE",
    }
    defaults.update(overrides)
    return defaults
