"""Payload factories — one per entity, input fields only.

Each test runs against a fresh database, but a single test may create several
clients/stylists/products; the counters below keep unique fields (email, sku)
distinct within one test run.
"""
import itertools

_counter = itertools.count(1)


def _uid() -> int:
    return next(_counter)


def create_client_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "email": f"client{n}@example.com",
        "full_name": f"Client {n}",
        "region_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_style_profile_payload(**overrides) -> dict:
    defaults = {
        "quiz_top_size": 8,
        "quiz_bottom_size": 8,
        "quiz_shoe_size": 9,
        "price_tier": "MID",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Product {n}",
        "category": "TOP",
        "size": 8,
        "price_cents": 3000,
        "total_stock": 5,
    }
    defaults.update(overrides)
    return defaults


def create_stylist_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "email": f"stylist{n}@example.com",
        "name": f"Stylist {n}",
    }
    defaults.update(overrides)
    return defaults


def schedule_fix_payload(expected_client_version: int, **overrides) -> dict:
    defaults = {"expected_client_version": expected_client_version}
    defaults.update(overrides)
    return defaults


def create_hold_payload(start_date: str, end_date: str, **overrides) -> dict:
    defaults = {"start_date": start_date, "end_date": end_date}
    defaults.update(overrides)
    return defaults


def create_purchase_payload(product_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults
