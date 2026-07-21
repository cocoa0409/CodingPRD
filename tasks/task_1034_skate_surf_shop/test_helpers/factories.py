"""Payload factories — one per entity, input fields only (PRD Section 3/4)."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_product_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Product {n}",
        "category": "DECK",
        "unit_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_rentable_product_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "sku": f"RENT-{n}",
        "name": f"Rentable {n}",
        "category": "SURFBOARD",
        "unit_price_cents": 50000,
        "rental_day_rate_cents": 2000,
        "is_rentable": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "email": f"member{n}@example.com",
        "full_name": f"Member {n}",
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Coach {n}",
        "discipline": "SURF",
    }
    defaults.update(overrides)
    return defaults


def create_rental_asset_payload(product_id, **overrides) -> dict:
    n = _uniq()
    defaults = {
        "product_id": product_id,
        "asset_tag": f"ASSET-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_lesson_payload(coach_id, customer_id, **overrides) -> dict:
    defaults = {
        "coach_id": coach_id,
        "customer_id": customer_id,
        "discipline": "SURF",
        "start_at": "2026-07-08T10:00:00Z",
        "end_at": "2026-07-08T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(customer_id, rental_asset_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "rental_asset_id": rental_asset_id,
        "start_at": "2026-07-02T00:00:00Z",
        "end_at": "2026-07-05T00:00:00Z",
        "deposit_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_board_build_payload(customer_id, components, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "components": components,
    }
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(customer_id, parts, labor_cents, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "board_description": "Regrip and wax",
        "parts": parts,
        "labor_cents": labor_cents,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(customer_id, mode="TRADE_IN", **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "item_description": "Used gear",
        "mode": mode,
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, product_id, quantity=1, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Event {n}",
        "sponsor": "BrandX",
        "venue": "North Beach",
        "start_at": "2026-07-10T00:00:00Z",
        "capacity": 10,
        "entry_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_event_entry_payload(event_id, customer_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults
