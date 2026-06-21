"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict so overrides do not bleed across tests.
"""
import itertools


# A counter that produces stable but unique phone numbers / emails inside one
# test run (the test server is restarted before every pytest test, so the
# counter resets back to 0 each time the process loads — no cross-test bleed).
_phone_counter = itertools.count(10000)
_email_counter = itertools.count(10000)


def fresh_phone(prefix: str = "+1202555") -> str:
    return f"{prefix}{next(_phone_counter):04d}"


def fresh_email(local_prefix: str = "user") -> str:
    return f"{local_prefix}{next(_email_counter)}@example.com"


# ---- Owner ----

def create_owner_payload(**overrides) -> dict:
    defaults = {
        "email": fresh_email("owner"),
        "full_name": "Test Owner",
        "phone": fresh_phone(),
    }
    defaults.update(overrides)
    return defaults


# ---- Sitter ----

def create_sitter_payload(**overrides) -> dict:
    defaults = {
        "email": fresh_email("sitter"),
        "full_name": "Test Sitter",
        "phone": fresh_phone(),
    }
    defaults.update(overrides)
    return defaults


# ---- BackgroundCheck ----

def create_background_check_payload(sitter_id: str, **overrides) -> dict:
    defaults = {
        "sitter_id": sitter_id,
        "provider": "CHECKR",
    }
    defaults.update(overrides)
    return defaults


def flag_background_check_payload(reason: str = "verification failed", **overrides) -> dict:
    defaults = {"flagged_reason": reason}
    defaults.update(overrides)
    return defaults


# ---- Pet ----

def create_pet_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "name": "Rex",
        "species": "DOG",
        "weight_kg": 10.0,
    }
    defaults.update(overrides)
    return defaults


# ---- EmergencyContact ----

def create_emergency_contact_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "full_name": "Emergency Person",
        "phone": fresh_phone(),
        "relationship": "SPOUSE",
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


# ---- MeetAndGreet ----

def create_meet_and_greet_payload(owner_id: str, sitter_id: str, pet_id: str,
                                   scheduled_at: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "sitter_id": sitter_id,
        "pet_id": pet_id,
        "scheduled_at": scheduled_at,
    }
    defaults.update(overrides)
    return defaults


# ---- Booking ----

def create_booking_payload(owner_id: str, sitter_id: str, pet_id: str,
                            start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "sitter_id": sitter_id,
        "pet_id": pet_id,
        "service_type": "WALK_60MIN",
        "time_of_day": "STANDARD",
        "recurring_cadence": "NONE",
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def cancel_booking_payload(reason: str = "owner cancel", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def reject_booking_payload(reason: str = "sitter reject", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def complete_booking_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def emergency_terminate_payload(reason: str = "emergency", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---- KeyHandoff ----

def create_key_handoff_payload(booking_id: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "method": "IN_PERSON",
    }
    defaults.update(overrides)
    return defaults


# ---- GpsTrack ----

def create_gps_track_payload(booking_id: str, recorded_at: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "latitude": 40.7128,
        "longitude": -74.0060,
        "recorded_at": recorded_at,
    }
    defaults.update(overrides)
    return defaults


# ---- InsuranceClaim ----

def create_insurance_claim_payload(booking_id: str, claim_amount_cents: int = 15000,
                                    **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "claim_amount_cents": claim_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_insurance_claim_payload(approved_amount_cents: int, **overrides) -> dict:
    defaults = {"approved_amount_cents": approved_amount_cents}
    defaults.update(overrides)
    return defaults


def deny_insurance_claim_payload(denied_reason: str = "insufficient evidence",
                                   **overrides) -> dict:
    defaults = {"denied_reason": denied_reason}
    defaults.update(overrides)
    return defaults
