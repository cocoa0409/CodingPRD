"""Payload factories — one per entity, input fields only."""


def create_product_payload(**overrides) -> dict:
    """Input fields for POST /products. allergen_tags and shelf_life_days are optional."""
    payload = {
        "name": "Chamomile",
        "category": "HERB",
        "kind": "SIMPLE",
        "unit_price_cents_per_gram": 2.5,
        "tare_default_grams": 8,
        "allergen_tags": [],
    }
    payload.update(overrides)
    return payload


def create_blend_component_payload(**overrides) -> dict:
    """Input fields for POST /blend-components."""
    payload = {
        "blend_product_id": None,
        "component_product_id": None,
        "weight_ratio_bps": 10000,
    }
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(**overrides) -> dict:
    """Input fields for POST /inventory-lots."""
    payload = {
        "product_id": None,
        "lot_code": "LOT-1",
        "grams_received": 500,
        "received_at": "2026-06-01T00:00:00Z",
        "best_by": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_production_line_payload(**overrides) -> dict:
    payload = {"name": "Line 1"}
    payload.update(overrides)
    return payload


def create_batch_payload(**overrides) -> dict:
    """Input fields for POST /batches."""
    payload = {
        "blend_product_id": None,
        "production_line_id": None,
        "target_output_grams": 100,
        "scheduled_start": "2026-07-10T08:00:00Z",
        "scheduled_end": "2026-07-10T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_labeling_station_payload(**overrides) -> dict:
    payload = {"name": "Station A"}
    payload.update(overrides)
    return payload


def create_tin_run_payload(**overrides) -> dict:
    """Input fields for POST /tin-runs."""
    payload = {
        "labeling_station_id": None,
        "product_ids": [],
        "scheduled_start": "2026-07-10T08:00:00Z",
        "scheduled_end": "2026-07-10T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_wholesale_account_payload(**overrides) -> dict:
    """Input fields for POST /wholesale-accounts. tier is optional (defaults BRONZE)."""
    payload = {
        "business_name": "Acme Co",
        "credit_limit_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_order_payload(**overrides) -> dict:
    """Input fields for POST /orders. allergen_ack is optional (defaults false)."""
    payload = {
        "wholesale_account_id": None,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(**overrides) -> dict:
    """Input fields for POST /orders/{id}/lines."""
    payload = {
        "product_id": None,
        "requested_grams": 100,
    }
    payload.update(overrides)
    return payload
