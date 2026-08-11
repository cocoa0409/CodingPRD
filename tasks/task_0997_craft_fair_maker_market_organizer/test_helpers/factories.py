"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid

from .constants import (
    CLOCK_START, WINDOW_START, WINDOW_END, EVENT_OPENS, EVENT_CLOSES,
)


def create_maker_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Fair",
        "opens_at": EVENT_OPENS,
        "closes_at": EVENT_CLOSES,
        "venue_capacity": 100,
        "application_window_start": WINDOW_START,
        "application_window_end": WINDOW_END,
        "jury_quorum": 2,
        "commission_pct_standard": 0.10,
        "commission_pct_anchor": 0.05,
    }
    defaults.update(overrides)
    return defaults


def create_booth_zone_payload(**overrides) -> dict:
    defaults = {
        "label": "Hall",
        "weather_exposure": "INDOOR",
        "category": "CERAMICS",
        "category_cap": 3,
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(**overrides) -> dict:
    defaults = {
        "code": "H-01",
        "tier": "STANDARD",
        "footprint_sqm": 9,
        "price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_profile_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Vendor",
        "contact_email": f"vendor-{uuid.uuid4().hex[:10]}@example.com",
        "home_region": "WA",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(vendor_profile_id, **overrides) -> dict:
    defaults = {
        "vendor_profile_id": vendor_profile_id,
        "requested_category": "CERAMICS",
        "requested_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_jury_score_payload(**overrides) -> dict:
    defaults = {
        "craftsmanship": 8,
        "originality": 8,
        "booth_presentation": 8,
    }
    defaults.update(overrides)
    return defaults


def create_decide_payload(outcome, expected_event_version) -> dict:
    return {"outcome": outcome, "expected_event_version": expected_event_version}


def create_ticket_payload(**overrides) -> dict:
    defaults = {
        "purchaser_email": f"buyer-{uuid.uuid4().hex[:8]}@example.com",
        "kind": "GA",
        "price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_load_slot_payload(booth_assignment_id, **overrides) -> dict:
    defaults = {
        "booth_assignment_id": booth_assignment_id,
        "kind": "LOAD_IN",
        "starts_at": "2026-06-01T09:00:00Z",
        "ends_at": "2026-06-01T11:00:00Z",
        "bay": "NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(booth_assignment_id, gross_cents, **overrides) -> dict:
    defaults = {
        "booth_assignment_id": booth_assignment_id,
        "gross_cents": gross_cents,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_approve_payload(expected_settlement_version) -> dict:
    return {"expected_settlement_version": expected_settlement_version}
