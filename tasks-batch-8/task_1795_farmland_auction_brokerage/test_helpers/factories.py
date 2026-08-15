"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import (
    AUCTION_END,
    AUCTION_START,
    QUALIFICATION_EXPIRY,
    TARGET_CLOSING_DATE,
)


def create_seller_payload(**overrides) -> dict:
    defaults = {"full_name": "Seller One", "email": "s1@x.com"}
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {"full_name": "Agent One", "license_number": "LIC-001"}
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Buyer One",
        "email": "b1@x.com",
        "proof_of_funds_amount": 2000000,
    }
    defaults.update(overrides)
    return defaults


def qualify_buyer_payload(**overrides) -> dict:
    defaults = {"qualification_expires_at": QUALIFICATION_EXPIRY}
    defaults.update(overrides)
    return defaults


def create_listing_payload(seller_id: str, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "title": "L1",
        "county": "Dallas",
        "state_code": "IA",
        "total_gross_acres": 100,
        "packaging_strategy": "WHOLE",
        "reserve_price_total": 770000,
    }
    defaults.update(overrides)
    return defaults


def create_tract_payload(listing_id: str, expected_listing_version: int, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "tract_number": 1,
        "gross_acres": 100,
        "tillable_acres": 90,
        "soil_productivity_index": 80,
        "min_price": 700000,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_comparable_payload(**overrides) -> dict:
    defaults = {
        "county": "Dallas",
        "state_code": "IA",
        "sale_date": "2026-01-15T00:00:00Z",
        "sale_price_total": 900000,
        "gross_acres": 100,
        "tillable_acres": 95,
        "soil_productivity_index": 80,
    }
    defaults.update(overrides)
    return defaults


def create_auction_payload(listing_id: str, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "method": "ONLINE",
        "scheduled_start": AUCTION_START,
        "scheduled_end": AUCTION_END,
    }
    defaults.update(overrides)
    return defaults


def place_bid_payload(auction_id: str, amount, tract_ids, expected_auction_version: int, **overrides) -> dict:
    defaults = {
        "auction_id": auction_id,
        "amount": amount,
        "tract_ids": list(tract_ids),
        "expected_auction_version": expected_auction_version,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount, **overrides) -> dict:
    defaults = {"amount": amount}
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(tract_id: str, **overrides) -> dict:
    defaults = {
        "tract_id": tract_id,
        "tenant_name": "Tenant A",
        "lease_start_date": "2025-03-01T00:00:00Z",
        "lease_end_date": "2026-10-15T00:00:00Z",
        "annual_rent": 18000,
    }
    defaults.update(overrides)
    return defaults


def create_rights_payload(tract_id: str, **overrides) -> dict:
    defaults = {
        "tract_id": tract_id,
        "mineral_rights": "CONVEYED",
        "wind_rights": "CONVEYED",
    }
    defaults.update(overrides)
    return defaults


def create_closing_payload(auction_id: str, **overrides) -> dict:
    defaults = {
        "auction_id": auction_id,
        "target_closing_date": TARGET_CLOSING_DATE,
        "payoff_amount": 0,
    }
    defaults.update(overrides)
    return defaults


def track_event_payload(axis: str, event: str, **overrides) -> dict:
    defaults = {"axis": axis, "event": event}
    defaults.update(overrides)
    return defaults


def create_statement_payload(closing_id: str, variant: str, **overrides) -> dict:
    defaults = {"closing_id": closing_id, "variant": variant}
    defaults.update(overrides)
    return defaults
