"""Payload factories — one per entity, input fields only."""


DEFAULTS = {
    "HOME_NAME": "Test Funeral Home",
    "CONTACT_EMAIL": "contact@example.com",
    "VENUE_NAME": "Main Chapel",
    "CAPACITY": 100,
    "TURNAROUND_MINUTES": 0,
    "OPERATOR_NAME": "Test Operator",
    "DECEDENT_NAME": "Test Decedent",
    "SCHEDULED_START": "2026-06-01T10:00:00Z",
    "SCHEDULED_END": "2026-06-01T12:00:00Z",
    "DONOR_NAME": "Test Donor",
    "GROSS_AMOUNT_CENTS": 1000,
    "TRIBUTE_TITLE": "In Loving Memory",
    "PHOTO_COUNT": 10,
    "AUTHOR_NAME": "Test Guest",
    "MESSAGE": "With deepest sympathy.",
}


def create_funeral_home_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["HOME_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "initial_credits": 0,
    }
    payload.update(overrides)
    return payload


def create_venue_payload(home_id, **overrides) -> dict:
    payload = {
        "home_id": home_id,
        "name": DEFAULTS["VENUE_NAME"],
        "capacity": DEFAULTS["CAPACITY"],
        "turnaround_minutes": DEFAULTS["TURNAROUND_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_operator_payload(home_id, **overrides) -> dict:
    payload = {
        "home_id": home_id,
        "full_name": DEFAULTS["OPERATOR_NAME"],
        "skill": "CAMERA",
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(home_id, venue_id, **overrides) -> dict:
    payload = {
        "home_id": home_id,
        "venue_id": venue_id,
        "decedent_name": DEFAULTS["DECEDENT_NAME"],
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
    }
    payload.update(overrides)
    return payload


def create_venue_booking_payload(order_id, venue_id, window_start, window_end,
                                 expected_order_version, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "venue_id": venue_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_camera_assignment_payload(order_id, operator_id, role="CAMERA", **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "operator_id": operator_id,
        "role": role,
    }
    payload.update(overrides)
    return payload


def create_guestbook_entry_payload(order_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "author_name": DEFAULTS["AUTHOR_NAME"],
        "message": DEFAULTS["MESSAGE"],
    }
    payload.update(overrides)
    return payload


def create_donation_payload(order_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "donor_name": DEFAULTS["DONOR_NAME"],
        "gross_amount_cents": DEFAULTS["GROSS_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_tribute_video_payload(order_id, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "title": DEFAULTS["TRIBUTE_TITLE"],
        "photo_count": DEFAULTS["PHOTO_COUNT"],
    }
    payload.update(overrides)
    return payload
