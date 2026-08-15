"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_market_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "market_code": f"MKT{n:03d}",
        "display_name": f"Market {n}",
        "pricing_multiplier_bps": 10000,
        "standard_turnaround_hours": 48,
    }
    defaults.update(overrides)
    return defaults


def create_photographer_payload(market_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "market_id": market_id,
        "full_name": f"Photographer {n}",
        "email": f"photog{n}@example.com",
        "equipment_packages": ["STANDARD"],
    }
    defaults.update(overrides)
    return defaults


def create_client_agent_payload(home_market_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "brokerage_name": f"Brokerage {n}",
        "full_name": f"Agent {n}",
        "email": f"agent{n}@example.com",
        "home_market_id": home_market_id,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(market_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "order_ref": f"ORD-{n:04d}",
        "market_id": market_id,
        "property_address": f"{n} Test St",
        "equipment_package": "STANDARD",
        "photo_count": 20,
        "scheduled_start_utc": "2026-08-10T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults
