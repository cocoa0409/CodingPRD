"""Payload factories — one per entity, input fields only.

Every factory accepts **overrides so a test can control the values it asserts on
and leave the rest at sensible defaults. Computed/system fields are never set.
"""

# Default option lists used across product payloads.
STANDARD_FABRIC = {"code": "STANDARD", "surcharge_cents": 0}
VELVET_FABRIC = {"code": "VELVET", "surcharge_cents": 20000}
STD_SIZE = {"code": "STD", "surcharge_cents": 0}
QUEEN_SIZE = {"code": "QUEEN", "surcharge_cents": 0}


def create_product_payload(**overrides) -> dict:
    """A standard in-stock sofa: base 100000, STANDARD fabric / STD size."""
    defaults = {
        "sku": "SOFA-STD",
        "name": "Aspen Sofa",
        "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [dict(STANDARD_FABRIC)],
        "available_sizes": [dict(STD_SIZE)],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """A creditworthy customer that clears the financing gates by default."""
    defaults = {
        "full_name": "Test Buyer",
        "email": "buyer@example.com",
        "credit_score": 720,
        "monthly_income_cents": 9000000,
        "existing_monthly_obligations_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_tier": "THRESHOLD",
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(order_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "product_id": product_id,
        "fabric_code": "STANDARD",
        "size_code": "STD",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_financing_plan_payload(order_id: str, expected_order_version: int,
                                  **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "plan_type": "INSTALLMENT",
        "term_months": 12,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {
        "region_code": "NORTH",
        "service_date": "2026-03-01T00:00:00Z",
        "shift_start_minute": 480,
        "shift_end_minute": 1080,
        "capacity_units": 5,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_stop_payload(route_id: str, order_id: str,
                                 expected_route_version: int, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "order_id": order_id,
        "window_start_minute": 600,
        "window_end_minute": 660,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def create_protection_plan_payload(order_line_id: str, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "tier": "BASIC",
        "coverage_years": 2,
    }
    defaults.update(overrides)
    return defaults


def create_return_request_payload(order_line_id: str, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "reason": "CHANGED_MIND",
    }
    defaults.update(overrides)
    return defaults
