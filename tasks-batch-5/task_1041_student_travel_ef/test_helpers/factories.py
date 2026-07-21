"""Payload factories — one per entity, input fields only.

Each factory returns the minimal valid create payload and accepts **overrides.
"""
import uuid

# Canonical dates used across scenarios (depart 2026-11-01, return 2026-11-08).
DEFAULT_DEPART_DATE = "2026-11-01T00:00:00Z"
DEFAULT_RETURN_DATE = "2026-11-08T00:00:00Z"
DEFAULT_ENROLLMENT_DEADLINE = "2026-09-01T00:00:00Z"
DEFAULT_EARLY_BIRD_CUTOFF = "2026-08-01T00:00:00Z"
DEFAULT_DOB = "2010-05-01T00:00:00Z"
DEFAULT_PASSPORT_EXPIRY = "2031-01-01T00:00:00Z"


def unique_email(prefix="leader"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@lincoln.edu"


def create_tour_payload(**overrides) -> dict:
    defaults = {
        "name": "Rome Classics",
        "destination": "Italy",
        "nights": 7,
        "base_price_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def create_group_leader_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ms Rivera",
        "email": unique_email(),
        "school_name": "Lincoln HS",
    }
    defaults.update(overrides)
    return defaults


def create_departure_payload(tour_id, group_leader_id, **overrides) -> dict:
    defaults = {
        "tour_id": tour_id,
        "group_leader_id": group_leader_id,
        "depart_date": DEFAULT_DEPART_DATE,
        "return_date": DEFAULT_RETURN_DATE,
        "enrollment_deadline": DEFAULT_ENROLLMENT_DEADLINE,
        "early_bird_cutoff": DEFAULT_EARLY_BIRD_CUTOFF,
        "capacity": 30,
        "price_per_traveler_cents": 250000,
        "min_to_guarantee": 10,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(departure_id, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "traveler_name": "Sam Lee",
        "traveler_dob": DEFAULT_DOB,
        "traveler_gender": "MALE",
    }
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(enrollment_id, expected_enrollment_version, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "installment_count": 1,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(payment_plan_id, amount_cents, **overrides) -> dict:
    defaults = {
        "payment_plan_id": payment_plan_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_permission_form_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "passport_number": "X1234567",
        "passport_expiry": DEFAULT_PASSPORT_EXPIRY,
        "guardian_consent": True,
    }
    defaults.update(overrides)
    return defaults


def create_chaperone_payload(departure_id, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "full_name": "Chap Person",
        "email": unique_email("chap"),
    }
    defaults.update(overrides)
    return defaults


def create_rooming_payload(departure_id, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "room_label": "R-201",
        "room_type": "DOUBLE",
        "room_gender": "MALE",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": "Hotel Colosseo",
        "service_type": "HOTEL",
        "city": "Rome",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_booking_payload(departure_id, supplier_id, service_window_start,
                                    service_window_end, **overrides) -> dict:
    defaults = {
        "departure_id": departure_id,
        "supplier_id": supplier_id,
        "service_window_start": service_window_start,
        "service_window_end": service_window_end,
        "room_block": 5,
        "cost_cents": 250000,
    }
    defaults.update(overrides)
    return defaults
