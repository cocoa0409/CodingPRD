"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VENUE_NAME": "Test Venue",
    "CLOSING_TIME_UTC": "2026-03-16T06:00:00Z",
    "FIRE_CODE_CAPACITY": 10,
}


def create_venue_payload(**overrides) -> dict:
    """Venue create. Required: name, fire_code_capacity, closing_time_utc.
    Optional (server defaults if omitted): last_call_offset_minutes,
    cover_base_cents, cover_surge_pct, max_alcohol_strikes."""
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "fire_code_capacity": DEFAULTS["FIRE_CODE_CAPACITY"],
        "closing_time_utc": DEFAULTS["CLOSING_TIME_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_promoter_payload(venue_id: str, **overrides) -> dict:
    """Promoter create. Required: venue_id, name, comp_budget_cents.
    Optional: guest_discount_pct (default 0.5)."""
    defaults = {
        "venue_id": venue_id,
        "name": "Test Promoter",
        "comp_budget_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_guest_list_payload(venue_id: str, **overrides) -> dict:
    """Guest-list add. Required: venue_id, guest_name, party_size.
    Optional: promoter_id (default null/house), comp_value_cents (default 0)."""
    defaults = {
        "venue_id": venue_id,
        "guest_name": "Test Guest",
        "party_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_id_check_payload(venue_id: str, **overrides) -> dict:
    """ID check. Required: venue_id, patron_name, date_of_birth, id_expiry."""
    defaults = {
        "venue_id": venue_id,
        "patron_name": "Test Patron",
        "date_of_birth": "1990-01-01",
        "id_expiry": "2030-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(venue_id: str, id_check_id: str, expected_venue_version: int, **overrides) -> dict:
    """Admit. Required: venue_id, id_check_id, expected_venue_version.
    Optional: guest_list_entry_id."""
    defaults = {
        "venue_id": venue_id,
        "id_check_id": id_check_id,
        "expected_venue_version": expected_venue_version,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(venue_id: str, expected_venue_version: int, **overrides) -> dict:
    """Book reservation. Required: venue_id, table_label, party_size,
    window_start_utc, window_end_utc, spend_minimum_cents, expected_venue_version.
    Optional: deposit_cents (default 0)."""
    defaults = {
        "venue_id": venue_id,
        "table_label": "VIP-1",
        "party_size": 4,
        "window_start_utc": "2026-01-01T00:00:00Z",
        "window_end_utc": "2026-03-16T05:00:00Z",
        "spend_minimum_cents": 10000,
        "expected_venue_version": expected_venue_version,
    }
    defaults.update(overrides)
    return defaults


def create_tab_payload(venue_id: str, **overrides) -> dict:
    """Open tab. Required: venue_id, patron_name, preauth_cents.
    Optional: reservation_id (walk-up if null), gratuity_pct (default 0.2)."""
    defaults = {
        "venue_id": venue_id,
        "patron_name": "Test Patron",
        "preauth_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_tab_item_payload(**overrides) -> dict:
    """Add tab item. Required: name, category, qty, unit_price_cents."""
    defaults = {
        "name": "Test Item",
        "category": "FOOD",
        "qty": 1,
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(venue_id: str, **overrides) -> dict:
    """File incident. Required: venue_id, severity, action, narrative.
    Optional: subject_entry_id."""
    defaults = {
        "venue_id": venue_id,
        "severity": "MINOR",
        "action": "WARNING",
        "narrative": "Test incident narrative",
    }
    defaults.update(overrides)
    return defaults
