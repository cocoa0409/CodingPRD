"""Payload factories — one per entity, input fields only.

Each factory supplies PRD-consistent defaults and accepts **overrides so a test
can control just the values it cares about.
"""


def create_farm_payload(**overrides) -> dict:
    """POST /farms body (PRD §3.1)."""
    payload = {
        "name": "Green Acres",
        "region_code": "R1",
        "commission_pct": 0.15,
        "snap_authorized": True,
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """POST /farms/{id}/products body (PRD §3.1). Defaults to a FIXED product."""
    payload = {
        "name": "Eggs",
        "category": "DAIRY",
        "pricing_mode": "FIXED",
        "unit_price_cents": 400,
        "snap_eligible": False,
    }
    payload.update(overrides)
    return payload


def weight_product_payload(**overrides) -> dict:
    """A WEIGHT-priced product body (PRD §3.1: price_per_kg_cents + estimated_weight_kg)."""
    payload = {
        "name": "Heirloom Tomatoes",
        "category": "PRODUCE",
        "pricing_mode": "WEIGHT",
        "price_per_kg_cents": 800,
        "estimated_weight_kg": 0.5,
        "snap_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(**overrides) -> dict:
    """POST /market-cycles body (PRD §3.2). Strictly increasing instants."""
    payload = {
        "cycle_code": "C1",
        "region_code": "R1",
        "order_open_at": "2026-06-02T00:00:00Z",
        "order_cutoff_at": "2026-06-05T00:00:00Z",
        "fulfillment_date": "2026-06-06T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_offering_payload(product_id, **overrides) -> dict:
    """POST /market-cycles/{id}/offerings body (PRD §3.3)."""
    payload = {
        "product_id": product_id,
        "offered_qty": 100,
    }
    payload.update(overrides)
    return payload


def create_hub_payload(**overrides) -> dict:
    """POST /pickup-hubs body (PRD §3.4)."""
    payload = {
        "name": "Downtown Pickup",
        "hub_type": "PICKUP",
        "slot_capacity": 100,
        "region_code": "R1",
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    """POST /customers body (PRD §3.4)."""
    payload = {
        "name": "Ada",
        "snap_balance_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(**overrides) -> dict:
    """POST /customers/{id}/subscriptions body (PRD §3.4)."""
    payload = {
        "pickup_hub_id": None,
        "box_size": "MEDIUM",
        "cadence": "WEEKLY",
        "price_cap_cents": 3000,
    }
    payload.update(overrides)
    return payload


def create_order_payload(market_cycle_id, pickup_hub_id, **overrides) -> dict:
    """POST /orders body (PRD §3.5). Defaults to a PICKUP order."""
    payload = {
        "market_cycle_id": market_cycle_id,
        "pickup_hub_id": pickup_hub_id,
        "fulfillment_type": "PICKUP",
    }
    payload.update(overrides)
    return payload


def add_line_payload(offering_id, requested_qty=1, **overrides) -> dict:
    """POST /orders/{id}/lines body (PRD §3.5)."""
    payload = {
        "offering_id": offering_id,
        "requested_qty": requested_qty,
    }
    payload.update(overrides)
    return payload


def pack_payload(**overrides) -> dict:
    """POST /order-lines/{id}/pack body (PRD §3.7)."""
    payload = {}
    payload.update(overrides)
    return payload


def create_settlement_payload(market_cycle_id, expected_farm_version, **overrides) -> dict:
    """POST /farms/{id}/settlements body (PRD §2.9, §3.9)."""
    payload = {
        "market_cycle_id": market_cycle_id,
        "expected_farm_version": expected_farm_version,
    }
    payload.update(overrides)
    return payload
