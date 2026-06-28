"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields with server-side defaults are
omitted unless overridden.
"""

DEFAULTS = {
    "STUDIO_NAME": "Test Studio",
    "ROOM_CAPACITY": 30,
    "ARTIST_NAME": "Test Artist",
    "CUSTOMER_FULL_NAME": "Test Customer",
    "BIRTHDATE": "1990-01-01T00:00:00Z",
    "EVENT_TITLE": "Test Class",
    "EVENT_START": "2026-04-05T10:00:00Z",
    "EVENT_END": "2026-04-05T12:00:00Z",
    "PRICE_PER_SEAT": 4500,
    "GIFT_CODE": "GC-TEST",
}


def create_studio_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STUDIO_NAME"],
        "room_capacity_seats": DEFAULTS["ROOM_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_artist_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["ARTIST_NAME"],
        "hourly_rate_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": "test@example.com",
        "full_name": DEFAULTS["CUSTOMER_FULL_NAME"],
        "birthdate": DEFAULTS["BIRTHDATE"],
    }
    payload.update(overrides)
    return payload


def create_event_payload(studio_id, **overrides) -> dict:
    payload = {
        "studio_id": studio_id,
        "title": DEFAULTS["EVENT_TITLE"],
        "event_type": "PUBLIC_CLASS",
        "start_utc": DEFAULTS["EVENT_START"],
        "end_utc": DEFAULTS["EVENT_END"],
        "seats_capacity": 10,
        "price_cents_per_seat": DEFAULTS["PRICE_PER_SEAT"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(event_id, artist_id, **overrides) -> dict:
    payload = {"event_id": event_id, "artist_id": artist_id}
    payload.update(overrides)
    return payload


def create_kit_batch_payload(event_id, sku="KIT-A", prepared_count=10, **overrides) -> dict:
    payload = {"event_id": event_id, "sku": sku, "prepared_count": prepared_count}
    payload.update(overrides)
    return payload


def create_reservation_payload(event_id, customer_id, expected_event_version,
                               booking_mode="PUBLIC", seats=1, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "customer_id": customer_id,
        "booking_mode": booking_mode,
        "seats": seats,
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return payload


def create_attendee_payload(reservation_id, full_name="Attendee", age_years=30,
                            **overrides) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "full_name": full_name,
        "age_years": age_years,
    }
    payload.update(overrides)
    return payload


def create_walk_in_payload(event_id, party_name="Walk-In Party", party_size=1,
                           **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "party_name": party_name,
        "party_size": party_size,
    }
    payload.update(overrides)
    return payload


def create_gift_card_payload(code=None, issued_value_cents=10000, **overrides) -> dict:
    payload = {
        "code": code if code is not None else DEFAULTS["GIFT_CODE"],
        "issued_value_cents": issued_value_cents,
    }
    payload.update(overrides)
    return payload


def credit_adjustment_payload(amount_cents, reason="adjustment", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def pay_payload(gift_card_ids=None, use_studio_credit=False, **overrides) -> dict:
    payload = {"use_studio_credit": use_studio_credit}
    if gift_card_ids is not None:
        payload["gift_card_ids"] = gift_card_ids
    payload.update(overrides)
    return payload
