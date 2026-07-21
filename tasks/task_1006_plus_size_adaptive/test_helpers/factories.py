"""Payload factories — one per input-carrying entity, input fields only."""

DEFAULTS = {
    "PRODUCT_NAME": "Adaptive Wrap Dress",
    "PRODUCT_CATEGORY": "DRESSES",
    "BASE_PRICE_CENTS": 6000,
    "SIZE_MIN": 10,
    "SIZE_MAX": 34,
    "VARIANT_SIZE": 22,
    "VARIANT_COLOR": "Navy",
    "SPECIALIST_NAME": "Test Stylist",
}


def register_customer_payload(**overrides) -> dict:
    """POST /customers/register — email, full_name, size_code required;
    adaptive_needs optional."""
    payload = {
        "email": "shopper@example.com",
        "full_name": "Test Shopper",
        "size_code": 22,
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """POST /products — name, category, base_price_cents, size_min, size_max
    required; adaptive_features, is_special_order, restock_fee_pct optional."""
    payload = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["PRODUCT_CATEGORY"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "size_min": DEFAULTS["SIZE_MIN"],
        "size_max": DEFAULTS["SIZE_MAX"],
    }
    payload.update(overrides)
    return payload


def create_variant_payload(**overrides) -> dict:
    """POST /products/{id}/variants — size_code, color required;
    price_delta_cents, inventory_on_hand optional."""
    payload = {
        "size_code": DEFAULTS["VARIANT_SIZE"],
        "color": DEFAULTS["VARIANT_COLOR"],
        "inventory_on_hand": 10,
    }
    payload.update(overrides)
    return payload


def create_specialist_payload(**overrides) -> dict:
    """POST /specialists — full_name, specialties required; buffer_minutes optional."""
    payload = {
        "full_name": DEFAULTS["SPECIALIST_NAME"],
        "specialties": ["ADAPTIVE"],
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(specialist_id, start_at, end_at, **overrides) -> dict:
    """POST /appointments — specialist_id, start_at, end_at required; topic optional."""
    payload = {
        "specialist_id": specialist_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def add_line_payload(variant_id, quantity=1, **overrides) -> dict:
    """POST /orders/{id}/lines — variant_id, quantity required."""
    payload = {"variant_id": variant_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_return_payload(order_id, return_type, line_ids, **overrides) -> dict:
    """POST /returns — order_id, return_type, line_ids required;
    exchange_variant_id, fit_verdict, refund_destination optional."""
    payload = {
        "order_id": order_id,
        "return_type": return_type,
        "line_ids": line_ids,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(plan_tier, **overrides) -> dict:
    """POST /box-subscriptions — plan_tier required; cadence optional."""
    payload = {"plan_tier": plan_tier}
    payload.update(overrides)
    return payload


def curate_shipment_payload(expected_subscription_version, item_variant_ids, **overrides) -> dict:
    """POST /box-subscriptions/{id}/shipments — expected_subscription_version,
    item_variant_ids required."""
    payload = {
        "expected_subscription_version": expected_subscription_version,
        "item_variant_ids": item_variant_ids,
    }
    payload.update(overrides)
    return payload
