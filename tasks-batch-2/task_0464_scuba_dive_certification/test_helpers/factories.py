"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Computed/system
fields (status, version, computed prices, timestamps stamped from the clock)
are never sent.
"""
import itertools

_email_counter = itertools.count(1)


def _unique_email(prefix="diver"):
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_diver_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Diver", "email": _unique_email()}
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Instructor", "rating": "INSTRUCTOR"}
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "title": "Open Water Cert",
        "course_type": "OPEN_WATER",
        "required_pool_sessions": 0,
        "required_open_water_sessions": 1,
        "price_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(diver_id, course_id, **overrides) -> dict:
    defaults = {"diver_id": diver_id, "course_id": course_id}
    defaults.update(overrides)
    return defaults


def create_waiver_payload(diver_id, medical_flagged=False, **overrides) -> dict:
    defaults = {"diver_id": diver_id, "medical_flagged": medical_flagged}
    defaults.update(overrides)
    return defaults


def create_session_payload(course_id, primary_instructor_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "session_type": "OPEN_WATER",
        "primary_instructor_id": primary_instructor_id,
        "starts_at": "2026-07-01T08:00:00Z",
        "ends_at": "2026-07-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_booking_payload(session_id, enrollment_id,
                                   expected_session_version, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "enrollment_id": enrollment_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_boat_payload(**overrides) -> dict:
    defaults = {"name": "Test Boat", "capacity": 10}
    defaults.update(overrides)
    return defaults


def create_dive_trip_payload(boat_id, **overrides) -> dict:
    defaults = {
        "boat_id": boat_id,
        "starts_at": "2026-07-01T08:00:00Z",
        "ends_at": "2026-07-01T12:00:00Z",
        "min_cert_level": "OPEN_WATER",
        "base_fare_cents": 12000,
        "fill_addon_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_trip_booking_payload(trip_id, diver_id, expected_trip_version,
                                **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "diver_id": diver_id,
        "expected_trip_version": expected_trip_version,
    }
    defaults.update(overrides)
    return defaults


def create_rental_agreement_payload(diver_id, **overrides) -> dict:
    defaults = {
        "diver_id": diver_id,
        "item_description": "BCD + regulator set",
        "daily_rate_cents": 4500,
        "deposit_cents": 20000,
        "scheduled_return_at": "2026-06-12T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fill_service_payload(diver_id, **overrides) -> dict:
    defaults = {
        "diver_id": diver_id,
        "gas": "AIR",
        "o2_pct": 21,
        "tank_capacity_liters": 10,
    }
    defaults.update(overrides)
    return defaults


def create_gear_service_order_payload(diver_id, service_type="VIP", **overrides) -> dict:
    defaults = {"diver_id": diver_id, "service_type": service_type}
    defaults.update(overrides)
    return defaults
