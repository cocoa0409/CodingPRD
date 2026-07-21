"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def next_seq() -> int:
    """Monotonic sequence for unique emails / line_codes within a test run."""
    return next(_counter)


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_type": "SOAP",
        "collection_name": "Autumn Hearth",
        "scent_family": "WOODY",
        "title": "Test Product",
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    defaults = {
        "size": "MEDIUM",
        "scent": "Amber",
        "list_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    seq = next_seq()
    defaults = {
        "quantity_produced": 100,
        "line_code": f"LINE_{seq}",
        "cure_starts_at": "2026-06-01T00:00:00Z",
        "cure_ends_at": "2026-06-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_drop_payload(**overrides) -> dict:
    defaults = {
        "season": "FALL_2026",
        "title": "Test Drop",
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-08-10T00:00:00Z",
        "listings": [],
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Bundle",
        "items": [],
        "bundle_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    seq = next_seq()
    defaults = {
        "email": f"customer{seq}@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "order_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(sku_id: str, batch_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "batch_id": batch_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(sku_id: str, quantity: int = 5, cadence_days: int = 30, **overrides) -> dict:
    defaults = {
        "sku_id": sku_id,
        "quantity": quantity,
        "cadence_days": cadence_days,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(reason: str = "changed mind", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults
