"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here; computed/system fields
(status, counts, credits_used, etc.) are server-managed and never sent.
"""

DEFAULTS = {
    "MEMBER_EMAIL": "member@example.com",
    "MEMBER_NAME": "Test Member",
    "HOME_STATE": "CA",
    "ROOM_NAME": "Reformer Studio A",
    "STATION_CAPACITY": 4,
    "TEACHER_NAME": "Test Teacher",
    "INTRO_NAME": "Two Weeks Unlimited",
    "INTRO_PRICE_CENTS": 3000,
    "INTRO_WINDOW_DAYS": 14,
    "MEMBERSHIP_PRICE_CENTS": 10000,
    "CLASS_PACK_PRICE_CENTS": 5000,
    "WORKSHOP_TITLE": "Test Workshop",
    "WORKSHOP_SEAT_CAPACITY": 8,
    "WORKSHOP_DEPOSIT_CENTS": 2000,
    "WORKSHOP_PRICE_CENTS": 8000,
}


def create_member_payload(**overrides) -> dict:
    payload = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_NAME"],
        "home_studio_state": DEFAULTS["HOME_STATE"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "room_type": "REFORMER",
        "station_capacity": DEFAULTS["STATION_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_teacher_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["TEACHER_NAME"],
        "certifications": ["VINYASA", "REFORMER"],
    }
    payload.update(overrides)
    return payload


def create_intro_offer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["INTRO_NAME"],
        "price_cents": DEFAULTS["INTRO_PRICE_CENTS"],
        "credits_total": -1,
        "window_days": DEFAULTS["INTRO_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_class_session_payload(room_id, teacher_id, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "teacher_id": teacher_id,
        "discipline": "REFORMER",
        "start_utc": "2026-02-20T10:00:00Z",
        "end_utc": "2026-02-20T11:00:00Z",
        "published_capacity": 4,
    }
    payload.update(overrides)
    return payload


def create_entitlement_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "kind": "MEMBERSHIP",
        "price_cents": DEFAULTS["MEMBERSHIP_PRICE_CENTS"],
        "credits_total": -1,
        "cycle_start_utc": "2026-02-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(member_id, class_session_id, entitlement_id,
                               expected_class_session_version, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "class_session_id": class_session_id,
        "entitlement_id": entitlement_id,
        "expected_class_session_version": expected_class_session_version,
    }
    payload.update(overrides)
    return payload


def create_workshop_payload(room_id, lead_teacher_id, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "lead_teacher_id": lead_teacher_id,
        "title": DEFAULTS["WORKSHOP_TITLE"],
        "kind": "WORKSHOP",
        "start_utc": "2026-03-01T09:00:00Z",
        "end_utc": "2026-03-01T12:00:00Z",
        "seat_capacity": DEFAULTS["WORKSHOP_SEAT_CAPACITY"],
        "deposit_cents": DEFAULTS["WORKSHOP_DEPOSIT_CENTS"],
        "price_cents": DEFAULTS["WORKSHOP_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id, workshop_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "workshop_id": workshop_id,
    }
    payload.update(overrides)
    return payload
