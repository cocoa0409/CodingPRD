"""Payload factories — one per entity, input fields only.

Only fields the PRD marks as client-supplied input appear here. Optional input
fields (timezone, late_cancel_window_hours, rollover_cap, freeze_max_days,
intro_once_per_member, waitlist_capacity) are included with sensible defaults
because they steer the business rules under test; tests override them as needed.
"""

DEFAULTS = {
    "STUDIO_NAME": "Downtown",
    "STATE_CODE": "CA",
    "ROOM_NAME": "Room A",
    "PHYSICAL_CAPACITY": 10,
    "INSTRUCTOR_NAME": "Ina",
    "TEMPLATE_NAME": "Flow",
    "DURATION_MIN": 60,
    "CREDIT_COST": 5,
    "LATE_CANCEL_WINDOW_HOURS": 12,
    "PLAN_NAME": "20 Pack",
    "PRICE_CENTS": 8000,
    "GRANT_CREDITS": 20,
    "VALIDITY_DAYS": 60,
    "STARTS_AT": "2026-06-20T10:00:00Z",
    "SEAT_CAPACITY": 5,
}


def create_studio_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STUDIO_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ROOM_NAME"],
        "physical_capacity": DEFAULTS["PHYSICAL_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_instructor_payload(home_studio_id: str, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "home_studio_id": home_studio_id,
    }
    payload.update(overrides)
    return payload


def create_class_template_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TEMPLATE_NAME"],
        "duration_min": DEFAULTS["DURATION_MIN"],
        "credit_cost": DEFAULTS["CREDIT_COST"],
        "late_cancel_window_hours": DEFAULTS["LATE_CANCEL_WINDOW_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_package_plan_payload(kind: str = "CREDIT_PACK", **overrides) -> dict:
    payload = {
        "name": DEFAULTS["PLAN_NAME"],
        "kind": kind,
        "price_cents": DEFAULTS["PRICE_CENTS"],
        "grant_credits": DEFAULTS["GRANT_CREDITS"],
        "validity_days": DEFAULTS["VALIDITY_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(home_studio_id: str, **overrides) -> dict:
    payload = {
        "email": "m1@x.com",
        "full_name": "M One",
        "home_studio_id": home_studio_id,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(plan_id: str, **overrides) -> dict:
    payload = {"plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_session_payload(studio_id: str, room_id: str, instructor_id: str,
                           template_id: str, **overrides) -> dict:
    payload = {
        "studio_id": studio_id,
        "room_id": room_id,
        "instructor_id": instructor_id,
        "template_id": template_id,
        "starts_at": DEFAULTS["STARTS_AT"],
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(membership_id: str, expected_session_version: int, **overrides) -> dict:
    payload = {
        "membership_id": membership_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload
