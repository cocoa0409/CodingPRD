"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix):
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "full_name": f"Test Customer {n}",
        "email": f"customer{n}@example.com",
        "phone": f"555-{n:04d}",
        "street_address": f"{n} Test Lane",
        "postal_code": "01010",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "product_kind": "CORD",
        "species": "OAK",
        "seasoned_grade": "KILN_DRIED",
        "base_price_cents": 40000,
        "moisture_ceiling_pct": 20.0,
        "available_qty": 100,
    }
    defaults.update(overrides)
    return defaults


def create_area_restriction_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Zone"),
        "postal_codes": ["55555"],
        "restricted_kinds": ["CORD"],
        "restricted_species": [],
        "enforcement_window_start": "11-01",
        "enforcement_window_end": "03-31",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, expected_customer_version, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "tier": "HEARTH",
        "season_year": 2026,
        "commitment_cord_equivalent": 2.0,
        "prepaid_cents": 0,
        "discount_pct": 0.05,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _uniq("R"),
        "depot_name": "Central Depot",
        "service_postal_prefixes": ["0"],
        "capacity_cord_equivalent": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_window_payload(route_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "service_date": "2026-08-15",
        "start_hour": 8,
        "end_hour": 18,
        "capacity_cord_equivalent": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, lines, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_street_address": "1 Test Street",
        "delivery_postal_code": "01010",
        "requested_delivery_date": "2026-08-15",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, quantity) -> dict:
    return {"product_id": product_id, "quantity": quantity}


def create_moisture_reading_payload(**overrides) -> dict:
    defaults = {"moisture_pct": 18.0}
    defaults.update(overrides)
    return defaults


def create_payment_payload(event_kind, amount_cents, external_ref=None, **overrides) -> dict:
    defaults = {
        "event_kind": event_kind,
        "amount_cents": amount_cents,
        "external_ref": external_ref or _uniq("ref"),
    }
    defaults.update(overrides)
    return defaults
