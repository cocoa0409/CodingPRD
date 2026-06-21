"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import (
    MENU_A_BASE_PRICE_PER_GUEST_CENTS,
    MENU_A_EST_INGREDIENT_PER_GUEST_CENTS,
    ZONE_A_TRAVEL_FEE_CENTS,
)


def create_chef_payload(**overrides) -> dict:
    """POST /chefs. Required: display_name, home_base_zip.
    Optional (server defaults): equipment_inventory=[], prep_buffer_minutes=90,
    max_bookings_per_day=2."""
    defaults = {
        "display_name": "Test Chef",
        "home_base_zip": "94101",
    }
    defaults.update(overrides)
    return defaults


def create_menu_payload(chef_id: str, **overrides) -> dict:
    """POST /menus. Required: chef_id, title, base_price_per_guest_cents,
    estimated_ingredient_per_guest_cents. Optional: min_party_size=2,
    max_party_size=12, allergen_tags=[], required_equipment=[]."""
    defaults = {
        "chef_id": chef_id,
        "title": "Tasting A",
        "base_price_per_guest_cents": MENU_A_BASE_PRICE_PER_GUEST_CENTS,
        "estimated_ingredient_per_guest_cents": MENU_A_EST_INGREDIENT_PER_GUEST_CENTS,
        "min_party_size": 2,
        "max_party_size": 12,
        "allergen_tags": [],
        "required_equipment": [],
    }
    defaults.update(overrides)
    return defaults


def create_travel_zone_payload(chef_id: str, **overrides) -> dict:
    """POST /travel-zones. Required: chef_id, zone_code, zip_prefixes, travel_fee_cents."""
    defaults = {
        "chef_id": chef_id,
        "zone_code": "ZONE_A",
        "zip_prefixes": ["941"],
        "travel_fee_cents": ZONE_A_TRAVEL_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_availability_block_payload(chef_id: str, **overrides) -> dict:
    """POST /availability-blocks (BLACKOUT). Required: chef_id, window_start_utc,
    window_end_utc."""
    defaults = {
        "chef_id": chef_id,
        "window_start_utc": "2026-09-05T17:00:00Z",
        "window_end_utc": "2026-09-05T23:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    """POST /clients. Required: full_name, email. Optional: allergen_restrictions=[],
    dietary_pattern=OMNIVORE."""
    defaults = {
        "full_name": "Test Client",
        "email": "client@ex.com",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(chef_id: str, client_id: str, menu_package_id: str, **overrides) -> dict:
    """POST /bookings. Required: chef_id, client_id, menu_package_id, party_size,
    service_zip, event_start_utc, event_end_utc."""
    defaults = {
        "chef_id": chef_id,
        "client_id": client_id,
        "menu_package_id": menu_package_id,
        "party_size": 6,
        "service_zip": "94110",
        "event_start_utc": "2026-08-15T18:00:00Z",
        "event_end_utc": "2026-08-15T22:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(booking_id: str, kind: str, amount_cents: int, **overrides) -> dict:
    """POST /payments. Required: booking_id, kind (DEPOSIT|BALANCE), amount_cents."""
    defaults = {
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_grocery_run_payload(booking_id: str, line_items=None, **overrides) -> dict:
    """POST /grocery-runs. Required: booking_id, line_items
    (array of {label, actual_cost_cents})."""
    if line_items is None:
        line_items = [{"label": "produce", "actual_cost_cents": 5000}]
    defaults = {
        "booking_id": booking_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_reschedule_request_payload(booking_id: str, **overrides) -> dict:
    """POST /reschedule-requests. Required: booking_id, proposed_event_start_utc,
    proposed_event_end_utc."""
    defaults = {
        "booking_id": booking_id,
        "proposed_event_start_utc": "2026-08-19T18:00:00Z",
        "proposed_event_end_utc": "2026-08-19T22:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recurring_plan_payload(chef_id: str, client_id: str, menu_package_id: str, **overrides) -> dict:
    """POST /recurring-plans. Required: chef_id, client_id, menu_package_id, party_size,
    service_zip, weekday, event_start_time_utc, duration_minutes. Optional: cadence_weeks=1."""
    defaults = {
        "chef_id": chef_id,
        "client_id": client_id,
        "menu_package_id": menu_package_id,
        "party_size": 4,
        "service_zip": "94110",
        "weekday": 2,
        "event_start_time_utc": "18:00:00",
        "duration_minutes": 180,
        "cadence_weeks": 1,
    }
    defaults.update(overrides)
    return defaults
