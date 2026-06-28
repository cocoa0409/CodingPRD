"""Payload factories — one per entity, input fields only (Banquet Event Order PRD §3)."""


def create_function_room_payload(**overrides) -> dict:
    """POST /function-rooms. turnover_buffer_minutes is optional (defaults to 60 server-side)."""
    defaults = {
        "name": "Grand Ballroom",
        "max_capacity": 200,
        "turnover_buffer_minutes": 60,
        "hourly_rental_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_hotel_room_block_payload(**overrides) -> dict:
    """POST /hotel-room-blocks."""
    defaults = {
        "block_name": "Test Block",
        "total_rooms": 10,
        "nightly_rate_cents": 19900,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    """POST /events. Only account_name, event_date, setup_style, expected_attendance are
    required; the four percentage fields are optional with server-side defaults."""
    defaults = {
        "account_name": "Test Account",
        "event_date": "2026-09-10",
        "setup_style": "THEATER",
        "expected_attendance": 100,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(function_room_id, start_utc, end_utc,
                           expected_event_version, **overrides) -> dict:
    """POST /events/{id}/bookings. setup_diagram_url optional; expected_event_version required (OCC)."""
    defaults = {
        "function_room_id": function_room_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_menu_line_payload(**overrides) -> dict:
    """POST /events/{id}/menu-lines. consumption_qty required for CONSUMPTION, omitted for PER_PERSON."""
    defaults = {
        "name": "Plated Filet",
        "pricing_mode": "PER_PERSON",
        "unit_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_service_line_payload(**overrides) -> dict:
    """POST /events/{id}/service-lines. gratuity_eligible optional (defaults to false)."""
    defaults = {
        "category": "AV",
        "description": "Projector + screen",
        "quantity": 1,
        "unit_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_room_block_link_payload(hotel_room_block_id, check_in_date, check_out_date,
                                   rooms_reserved, **overrides) -> dict:
    """POST /events/{id}/room-block-links."""
    defaults = {
        "hotel_room_block_id": hotel_room_block_id,
        "rooms_reserved": rooms_reserved,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_schedule_item_payload(amount_due_cents, **overrides) -> dict:
    """POST /events/{id}/payment-schedule-items."""
    defaults = {
        "label": "Deposit",
        "due_date": "2026-08-01",
        "amount_due_cents": amount_due_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, expected_event_version, **overrides) -> dict:
    """POST /events/{id}/payments. method defaults to WIRE; expected_event_version required (OCC)."""
    defaults = {
        "amount_cents": amount_cents,
        "method": "WIRE",
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults
