"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict of the fields a create endpoint accepts, with
sensible defaults that callers override via keyword arguments.
"""
import itertools

_sku_counter = itertools.count(1)


def unique_sku(prefix="SKU"):
    """Return a process-unique SKU so parallel-created products never collide."""
    return f"{prefix}-{next(_sku_counter)}"


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "name": "Test Bread",
        "category": "BREAD",
        "base_price_cents": 400,
        "shelf_life_hours": 12,
    }
    defaults.update(overrides)
    return defaults


def create_oven_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Oven",
        "capacity_trays": 20,
    }
    defaults.update(overrides)
    return defaults


def create_bake_plan_payload(**overrides) -> dict:
    defaults = {
        "production_date": "2026-06-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bake_plan_line_payload(**overrides) -> dict:
    defaults = {
        "par_qty": 20,
    }
    defaults.update(overrides)
    return defaults


def create_bake_lot_payload(**overrides) -> dict:
    defaults = {
        "baked_qty": 10,
        "produced_at": "2026-06-02T06:00:00Z",
        "slot_start": "2026-06-02T02:00:00Z",
        "slot_end": "2026-06-02T03:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_retail_sale_payload(**overrides) -> dict:
    defaults = {
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_wholesale_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Account",
        "credit_limit_cents": 1_000_000,
        "contract_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_standing_order_payload(**overrides) -> dict:
    defaults = {
        "qty_per_delivery": 10,
        "weekday_mask": ["MON"],
        "cutoff_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_order_payload(**overrides) -> dict:
    defaults = {
        "delivery_date": "2026-06-02T10:00:00Z",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "route_date": "2026-06-02T00:00:00Z",
        "driver_name": "Test Driver",
        "window_start": "2026-06-02T06:00:00Z",
        "window_end": "2026-06-02T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(**overrides) -> dict:
    defaults = {
        "sequence": 1,
        "arrival_window_start": "2026-06-02T08:00:00Z",
        "arrival_window_end": "2026-06-02T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults
