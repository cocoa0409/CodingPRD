"""Payload factories — one per entity, input fields only.

Only fields the client supplies on create (PRD Section 3 narratives) appear
here; computed/system fields are never sent.
"""

DEFAULTS = {
    "TUNNEL_NAME": "T1",
    "MAX_WEIGHT_KG": 120,
    "DEFAULT_CAPACITY": 4,
    "TURNAROUND_MINUTES": 15,
    "INSTRUCTOR_NAME": "Ivy",
    "CERT_LEVEL": "L2",
    "MEMBER_NAME": "Ada",
    "WEIGHT_KG": 80,
    "PACKAGE_NAME": "First Flight",
    "INCLUDED_MINUTES": 2,
    "BASE_PRICE_CENTS": 6000,
    "SESSION_START": "2026-05-10T10:00:00Z",
    "SESSION_END": "2026-05-10T10:30:00Z",
}


def create_tunnel_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TUNNEL_NAME"],
        "max_weight_kg": DEFAULTS["MAX_WEIGHT_KG"],
        "default_capacity": DEFAULTS["DEFAULT_CAPACITY"],
        "turnaround_minutes": DEFAULTS["TURNAROUND_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["INSTRUCTOR_NAME"],
        "cert_level": DEFAULTS["CERT_LEVEL"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MEMBER_NAME"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "experience_status": "FIRST_TIME",
    }
    payload.update(overrides)
    return payload


def create_waiver_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "weight_kg_declared": DEFAULTS["WEIGHT_KG"],
        "health_ok": True,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(member_id, tier, **overrides) -> dict:
    payload = {"member_id": member_id, "tier": tier}
    payload.update(overrides)
    return payload


def create_package_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PACKAGE_NAME"],
        "included_minutes": DEFAULTS["INCLUDED_MINUTES"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "min_experience": "FIRST_TIME",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(member_id, package_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "package_id": package_id,
        "booking_type": "WALK_IN",
        "party_size": 1,
    }
    payload.update(overrides)
    return payload


def create_session_payload(tunnel_id, **overrides) -> dict:
    payload = {
        "tunnel_id": tunnel_id,
        "start_utc": DEFAULTS["SESSION_START"],
        "end_utc": DEFAULTS["SESSION_END"],
        "capacity": DEFAULTS["DEFAULT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def assign_instructor_payload(instructor_id, expected_session_version, **overrides) -> dict:
    payload = {
        "instructor_id": instructor_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_flight_payload(booking_id, session_id, member_id, scheduled_minutes=2, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "session_id": session_id,
        "member_id": member_id,
        "scheduled_minutes": scheduled_minutes,
    }
    payload.update(overrides)
    return payload


def abort_flight_payload(flown_minutes=0, **overrides) -> dict:
    payload = {"flown_minutes": flown_minutes}
    payload.update(overrides)
    return payload


def create_coaching_payload(flight_id, instructor_id, minutes, **overrides) -> dict:
    payload = {"flight_id": flight_id, "instructor_id": instructor_id, "minutes": minutes}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
