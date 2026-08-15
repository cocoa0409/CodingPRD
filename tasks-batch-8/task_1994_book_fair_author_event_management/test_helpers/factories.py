"""Payload factories — one per entity, input fields only."""


def create_party_payload(**overrides) -> dict:
    defaults = {
        "kind": "SCHOOL",
        "name": "Ridgeview Elementary",
        "contact_email": "pta@ridgeview.example",
    }
    defaults.update(overrides)
    return defaults


def create_fair_payload(**overrides) -> dict:
    defaults = {
        "school_party_id": None,
        "title": "Fall Fair",
        "venue_key": "GYM",
        "planned_start_date": "2026-08-10",
        "planned_end_date": "2026-08-14",
        "signing_floor_capacity_units": 20,
        "promo_budget_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_venue_slot_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "venue_key": "GYM",
        "purpose": "FAIR_DAY",
        "start_at": "2026-08-10T08:00:00Z",
        "end_at": "2026-08-14T18:00:00Z",
        "setup_buffer_minutes": 60,
        "teardown_buffer_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "publisher_party_id": None,
        "discount_pct": 0.40,
        "return_cap_pct": 0.25,
        "restocking_fee_pct": 0.10,
        "markdown_allowance_pct": 0.20,
        "freight_responsibility": "ORGANIZER",
        "offer_expiry_hours": 72,
    }
    defaults.update(overrides)
    return defaults


def create_stock_line_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "agreement_id": None,
        "isbn": "9780000000001",
        "title": "Dragon Tales",
        "list_price_cents": 1000,
        "line_type": "FRONTLIST",
        "qty_committed": 10,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "author_party_id": None,
        "base_honorarium_cents": 10000,
        "travel_cap_cents": 2000,
        "bonus_threshold_attendees": 3,
        "bonus_base_cents": 1000,
        "bonus_per_attendee_cents": 100,
        "offer_expiry_hours": 72,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "booking_id": None,
        "fair_id": None,
        "mode": "TICKETED",
        "start_at": "2026-08-10T10:00:00Z",
        "end_at": "2026-08-10T11:00:00Z",
        "line_space_units": 5,
        "capacity_seats": 10,
        "admit_concurrent_cap": 5,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    defaults = {
        "session_id": None,
        "holder_name": "Kid One",
    }
    defaults.update(overrides)
    return defaults


def create_preorder_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "stock_line_id": None,
        "customer_name": "Ann",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "agreement_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_media_blast_payload(**overrides) -> dict:
    defaults = {
        "fair_id": None,
        "channel": "LOCAL_PAPER",
        "spend_cents": 300,
        "embargo_until": "2026-08-05T00:00:00Z",
        "content_summary": "Weekend feature piece",
    }
    defaults.update(overrides)
    return defaults
