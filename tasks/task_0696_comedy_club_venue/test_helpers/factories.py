"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults for the input (client-supplied)
fields of an entity and accepts **overrides for any value a test needs to pin.
Server-computed fields (status, computed money, version, ...) are never set here.
"""


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Test Venue",
        "settlement_currency": "USD",
    }
    payload.update(overrides)
    return payload


def create_show_payload(**overrides) -> dict:
    payload = {
        "title": "Test Show",
        "starts_at": "2026-04-01T03:00:00Z",
        "ends_at": "2026-04-01T05:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_section_payload(**overrides) -> dict:
    payload = {
        "kind": "GA",
        "label": "Main Floor",
        "ga_capacity": 100,
    }
    payload.update(overrides)
    return payload


def create_table_payload(**overrides) -> dict:
    payload = {
        "table_number": "T1",
        "seats": 4,
    }
    payload.update(overrides)
    return payload


def create_tier_payload(section_id, **overrides) -> dict:
    payload = {
        "section_id": section_id,
        "name": "GA Advance",
        "price_cents": 4500,
    }
    payload.update(overrides)
    return payload


def create_performer_payload(**overrides) -> dict:
    payload = {
        "stage_name": "Test Performer",
        "email": "performer@example.com",
        "standard_fee_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_lineup_slot_payload(show_id, performer_id, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "performer_id": performer_id,
        "slot_order": 1,
        "role": "HEADLINER",
        "offered_fee_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(show_id, section_id, tier_id, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "section_id": section_id,
        "tier_id": tier_id,
        "patron_id": "patron-default",
        "party_size": 2,
    }
    payload.update(overrides)
    return payload


def create_guest_list_entry_payload(show_id, host_performer_id, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "host_performer_id": host_performer_id,
        "guest_name": "VIP Guest",
        "party_size": 2,
    }
    payload.update(overrides)
    return payload


def create_server_payload(**overrides) -> dict:
    payload = {
        "name": "Test Server",
    }
    payload.update(overrides)
    return payload


def create_private_event_payload(show_id, **overrides) -> dict:
    payload = {
        "show_id": show_id,
        "client_name": "Test Client",
        "buyout_fee_cents": 500000,
    }
    payload.update(overrides)
    return payload
