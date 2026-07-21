"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. System- and
computed-source fields (status, totals, discounts, allocations, etc.) are set
by the server and are never sent.
"""

DEFAULTS = {
    "PRODUCT_NAME": "Test SKU",
    "FORM": "CAPSULE",
    "REGIMEN_GOALS": ["IMMUNITY"],
    "DSHEA_CLAIM_TYPE": "NONE",
    "UNIT_PRICE_CENTS": 1000,
    "LOT_NUMBER": "LOT-1",
    "EXPIRATION_DATE": "2027-01-01T00:00:00Z",
    "QUANTITY_RECEIVED": 10,
    "CUSTOMER_EMAIL": "test@x.com",
    "CUSTOMER_NAME": "Test Customer",
    "PRACTITIONER_NAME": "Dr Test",
    "LICENSE_NUMBER": "LIC-TEST",
    "BUNDLE_NAME": "Test Stack",
    "DISCOUNT_PCT": 0.15,
    "QUANTITY_PER_CYCLE": 1,
    "CADENCE_DAYS": 30,
    "FIRST_SHIP_DATE": "2026-08-01T00:00:00Z",
    "MAX_UNITS": 5,
    "RECOMMENDATION_EXPIRES_AT": "2026-12-31T00:00:00Z",
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "form": DEFAULTS["FORM"],
        "regimen_goals": list(DEFAULTS["REGIMEN_GOALS"]),
        "dshea_claim_type": DEFAULTS["DSHEA_CLAIM_TYPE"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
        "quantity_received": DEFAULTS["QUANTITY_RECEIVED"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "full_name": DEFAULTS["CUSTOMER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_practitioner_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PRACTITIONER_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_recommendation_payload(customer_id, product_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "expires_at": DEFAULTS["RECOMMENDATION_EXPIRES_AT"],
        "max_units": DEFAULTS["MAX_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(component_product_ids, **overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BUNDLE_NAME"],
        "component_product_ids": list(component_product_ids),
        "discount_pct": DEFAULTS["DISCOUNT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity_per_cycle": DEFAULTS["QUANTITY_PER_CYCLE"],
        "cadence_days": DEFAULTS["CADENCE_DAYS"],
        "first_ship_date": DEFAULTS["FIRST_SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    """One-off order. points_redeemed is optional (defaults to 0 server-side)."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, quantity, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id, order_line_id, quantity, reason, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "quantity": quantity,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
