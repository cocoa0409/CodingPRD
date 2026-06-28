"""Payload factories — one per entity, input fields only.

Each factory accepts **overrides so tests control exactly the fields they care
about. Only fields the PRD declares as client-supplied input are emitted.
"""

DEFAULTS = {
    "FAMILY_EMAIL": "family@example.com",
    "CONTACT_NAME": "Test Parent",
    "CHILD_NAME": "Test Child",
    "BIRTH_DATE": "2024-01-01",
    "PROGRAM_NAME": "Birds",
    "ROOM_NAME": "Room A",
    "INSTRUCTOR_NAME": "Ms. Lee",
    "TUITION_CENTS": 2500,
    "PHYSICAL_CAPACITY": 12,
    "SESSION_CAPACITY": 5,
    "CYCLE_ANCHOR_DAY": 1,
}


def create_family_payload(**overrides) -> dict:
    payload = {
        "account_email": DEFAULTS["FAMILY_EMAIL"],
        "primary_contact_name": DEFAULTS["CONTACT_NAME"],
    }
    payload.update(overrides)
    return payload


def create_child_payload(family_id, **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "full_name": DEFAULTS["CHILD_NAME"],
        "birth_date": DEFAULTS["BIRTH_DATE"],
    }
    payload.update(overrides)
    return payload


def create_membership_payload(family_id, tier="CORE", **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "tier": tier,
        "cycle_anchor_day": DEFAULTS["CYCLE_ANCHOR_DAY"],
    }
    payload.update(overrides)
    return payload


def create_program_payload(
    level_index=0,
    min_age_months=6,
    max_age_months=60,
    tuition_cents=None,
    **overrides,
) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "level_index": level_index,
        "min_age_months": min_age_months,
        "max_age_months": max_age_months,
        "tuition_cents": DEFAULTS["TUITION_CENTS"] if tuition_cents is None else tuition_cents,
        "participation_required": False,
    }
    payload.update(overrides)
    return payload


def create_room_payload(physical_capacity=None, **overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "physical_capacity": (
            DEFAULTS["PHYSICAL_CAPACITY"] if physical_capacity is None else physical_capacity
        ),
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(certified_level_indices=None, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "certified_level_indices": (
            [0] if certified_level_indices is None else certified_level_indices
        ),
        "buffer_minutes": 15,
    }
    payload.update(overrides)
    return payload


def create_session_payload(
    program_id, room_id, instructor_id,
    start_at="2026-05-10T09:00:00Z",
    end_at="2026-05-10T10:00:00Z",
    capacity=None,
    **overrides,
) -> dict:
    payload = {
        "program_id": program_id,
        "room_id": room_id,
        "instructor_id": instructor_id,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": DEFAULTS["SESSION_CAPACITY"] if capacity is None else capacity,
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(
    child_id, session_id, membership_id, expected_session_version,
    kind="RECURRING",
    **overrides,
) -> dict:
    payload = {
        "child_id": child_id,
        "session_id": session_id,
        "membership_id": membership_id,
        "kind": kind,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_facility_booking_payload(
    room_id, family_id, booking_type, expected_room_version,
    start_at="2026-05-10T09:00:00Z",
    end_at="2026-05-10T10:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "room_id": room_id,
        "family_id": family_id,
        "booking_type": booking_type,
        "start_at": start_at,
        "end_at": end_at,
        "expected_room_version": expected_room_version,
    }
    payload.update(overrides)
    return payload
