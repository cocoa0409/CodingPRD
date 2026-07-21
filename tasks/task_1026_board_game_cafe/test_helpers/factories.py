"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TABLE_LABEL": "T1",
    "MEMBER_EMAIL": "member@x.com",
    "MEMBER_NAME": "Test Member",
    "GAME_TITLE": "Catan",
    "TOURNAMENT_NAME": "Test Cup",
    "ROOM_NAME": "Test Room",
    "RETAIL_TITLE": "Test Game",
}


def create_table_payload(**overrides) -> dict:
    """Fully-priced MAIN table by default."""
    defaults = {
        "label": DEFAULTS["TABLE_LABEL"],
        "seats": 6,
        "half_hour_rate_cents": 500,
        "day_pass_cents": 6000,
        "cover_fee_cents": 300,
        "min_spend_cents": 2000,
        "zone": "MAIN",
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(table_id, start_at, end_at, **overrides) -> dict:
    defaults = {
        "table_id": table_id,
        "party_size": 2,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_fnb_order_payload(reservation_id, total_cents, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "description": "Snacks",
        "total_cents": total_cents,
    }
    defaults.update(overrides)
    return defaults


def create_game_copy_payload(barcode, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["GAME_TITLE"],
        "barcode": barcode,
        "replacement_value_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_checkout_payload(game_copy_id, reservation_id, **overrides) -> dict:
    defaults = {
        "game_copy_id": game_copy_id,
        "reservation_id": reservation_id,
    }
    defaults.update(overrides)
    return defaults


def create_tournament_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TOURNAMENT_NAME"],
        "game_title": "Catan",
        "format": "SINGLE_ELIM",
        "capacity": 8,
        "entry_fee_cents": 1000,
        "start_at": "2026-07-10T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(tournament_id, membership_id, **overrides) -> dict:
    defaults = {
        "tournament_id": tournament_id,
        "membership_id": membership_id,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ROOM_NAME"],
        "capacity": 20,
        "hourly_rate_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_private_booking_payload(room_id, start_at, end_at, expected_room_version, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "start_at": start_at,
        "end_at": end_at,
        "headcount": 8,
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_retail_order_payload(**overrides) -> dict:
    defaults = {
        "product_title": DEFAULTS["RETAIL_TITLE"],
        "fulfillment_type": "IN_STOCK",
        "quantity": 1,
        "unit_price_cents": 1500,
    }
    defaults.update(overrides)
    return defaults
