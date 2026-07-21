"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "RETREAT_NAME": "Test Retreat",
    "THEME": "YOGA",
    "LOCATION": "Bali",
    "START_DATE": "2026-09-01T00:00:00Z",
    "END_DATE": "2026-09-08T00:00:00Z",
    "CAPACITY": 20,
    "BASE_PRICE_CENTS": 150000,
}


def create_retreat_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RETREAT_NAME"],
        "theme": DEFAULTS["THEME"],
        "location": DEFAULTS["LOCATION"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "capacity": DEFAULTS["CAPACITY"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(retreat_id, **overrides) -> dict:
    payload = {
        "retreat_id": retreat_id,
        "kind": "LODGING",
        "tier": "STANDARD",
        "tier_delta_cents": 0,
        "bed_count": 4,
        "label": "R1",
    }
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    payload = {
        "email": "guest@example.com",
        "full_name": "Test Guest",
    }
    payload.update(overrides)
    return payload


def create_facilitator_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Facilitator",
        "email": "fac@example.com",
        "specialty": "Vinyasa",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(retreat_id, guest_id, room_id, party_size,
                           expected_retreat_version, **overrides) -> dict:
    payload = {
        "retreat_id": retreat_id,
        "guest_id": guest_id,
        "room_id": room_id,
        "party_size": party_size,
        "expected_retreat_version": expected_retreat_version,
    }
    payload.update(overrides)
    return payload


def create_waiver_payload(booking_id, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "health_disclosures": "none",
    }
    payload.update(overrides)
    return payload


def create_activity_slot_payload(retreat_id, facilitator_id, room_id,
                                 start_datetime, end_datetime, **overrides) -> dict:
    payload = {
        "retreat_id": retreat_id,
        "facilitator_id": facilitator_id,
        "room_id": room_id,
        "title": "Session",
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
    }
    payload.update(overrides)
    return payload


def create_shuttle_payload(retreat_id, **overrides) -> dict:
    payload = {
        "retreat_id": retreat_id,
        "direction": "ARRIVAL",
        "depart_datetime": "2026-08-31T12:00:00Z",
        "seat_capacity": 4,
    }
    payload.update(overrides)
    return payload


def create_transport_segment_payload(booking_id, shuttle_id, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "shuttle_id": shuttle_id,
    }
    payload.update(overrides)
    return payload


def create_addon_payload(**overrides) -> dict:
    payload = {
        "name": "Deep Tissue Massage",
        "category": "SPA",
        "price_cents": 25000,
    }
    payload.update(overrides)
    return payload


def create_booking_addon_payload(booking_id, addon_id, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "addon_id": addon_id,
    }
    payload.update(overrides)
    return payload
