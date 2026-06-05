"""Payload factories — one per entity, input fields only.

Each factory returns a dict suitable as a request body. Only fields the
client supplies are included; server/computed fields are never sent.
Emails and SKUs are made unique per call to keep tests independent.
"""
import uuid


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def create_catalog_item_payload(**overrides) -> dict:
    """POST /catalog-items. Required: sku, name, category, total_units,
    daily_rate_cents. Optionals carry PRD defaults if omitted."""
    defaults = {
        "sku": f"ITEM-{_unique_suffix()}",
        "name": "Test Item",
        "category": "CHAIR",
        "total_units": 100,
        "daily_rate_cents": 200,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """POST /customers. Required: email, full_name, phone."""
    defaults = {
        "email": f"cust-{_unique_suffix()}@example.com",
        "full_name": "Test Customer",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(customer_id, **overrides) -> dict:
    """POST /venues. Required: customer_id, name, address, delivery_zone."""
    defaults = {
        "customer_id": customer_id,
        "name": "Test Venue",
        "address": "1 Test St",
        "delivery_zone": "LOCAL",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    """POST /venues/{id}/certificates. Required: carrier_name, coverage_start,
    coverage_end, coverage_amount_cents."""
    defaults = {
        "carrier_name": "Acme Insurance",
        "coverage_start": "2026-08-01T00:00:00.000Z",
        "coverage_end": "2026-08-31T00:00:00.000Z",
        "coverage_amount_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    """POST /orders. Required: customer_id, fulfillment, event_start, event_end.
    venue_id required only for DELIVERY."""
    defaults = {
        "customer_id": customer_id,
        "fulfillment": "WILL_CALL",
        "event_start": "2026-06-01T00:00:00.000Z",
        "event_end": "2026-06-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def add_line_payload(item_id, quantity=1, **overrides) -> dict:
    """POST /orders/{id}/lines. Required: item_id, quantity."""
    defaults = {"item_id": item_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """POST /crews. Required: name. Optional: turnaround_minutes (default 0)."""
    defaults = {"name": "Test Crew"}
    defaults.update(overrides)
    return defaults


def create_delivery_run_payload(order_id, crew_id, leg="DROP_OFF", **overrides) -> dict:
    """POST /delivery-runs. Required: order_id, leg, crew_id, window_start, window_end."""
    defaults = {
        "order_id": order_id,
        "leg": leg,
        "crew_id": crew_id,
        "window_start": "2026-06-01T08:00:00.000Z",
        "window_end": "2026-06-01T09:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(**overrides) -> dict:
    """POST /weather-events. Required: delivery_zone, severity, effective_date."""
    defaults = {
        "delivery_zone": "LOCAL",
        "severity": "WARNING",
        "effective_date": "2026-06-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults
