"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides for the values a
test needs to control. Only fields whose source is client-supplied input appear
here; server-computed and system fields are never sent.
"""

DEFAULTS = {
    "PRODUCT_NAME": "Test Cake",
    "BASE_PRICE_CENTS": 10000,
    "BASE_LEAD_DAYS": 3,
    "TIER_LEVELS": 1,
    "PRODUCTION_DATE": "2026-06-20",
    "UNIT_CAPACITY": 50,
    "ORDER_CUTOFF_AT": "2026-06-15T00:00:00Z",
    "CLOCK": "2026-06-01T00:00:00Z",
    "ROUTE_NAME": "Test Route",
    "SERVICE_DATE": "2026-06-20",
    "STOP_MINUTES": 60,
}


def product_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "base_lead_days": DEFAULTS["BASE_LEAD_DAYS"],
        "tier_levels": DEFAULTS["TIER_LEVELS"],
        "allowed_option_codes": [],
        "declared_allergen_codes": ["GLUTEN"],
    }
    defaults.update(overrides)
    return defaults


def option_payload(option_code, surcharge_cents, **overrides) -> dict:
    defaults = {
        "option_code": option_code,
        "surcharge_cents": surcharge_cents,
        "introduces_allergen_codes": [],
        "dietary_exclusion_codes": [],
    }
    defaults.update(overrides)
    return defaults


def production_day_payload(**overrides) -> dict:
    defaults = {
        "production_date": DEFAULTS["PRODUCTION_DATE"],
        "unit_capacity": DEFAULTS["UNIT_CAPACITY"],
        "is_peak": False,
        "order_cutoff_at": DEFAULTS["ORDER_CUTOFF_AT"],
    }
    defaults.update(overrides)
    return defaults


def route_payload(**overrides) -> dict:
    defaults = {
        "route_name": DEFAULTS["ROUTE_NAME"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "stop_minutes": DEFAULTS["STOP_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def customer_payload(email, full_name="Test Customer", **overrides) -> dict:
    defaults = {"email": email, "full_name": full_name}
    defaults.update(overrides)
    return defaults


def order_payload(customer_id, product_id, production_day_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "production_day_id": production_day_id,
    }
    defaults.update(overrides)
    return defaults


def line_payload(units=1, selected_option_codes=None, requested_dietary_codes=None, **overrides) -> dict:
    defaults = {
        "units": units,
        "selected_option_codes": list(selected_option_codes or []),
        "requested_dietary_codes": list(requested_dietary_codes or []),
    }
    defaults.update(overrides)
    return defaults


def proof_payload(image_ref="proof-ref", **overrides) -> dict:
    defaults = {"image_ref": image_ref}
    defaults.update(overrides)
    return defaults


def deposit_payment_payload(**overrides) -> dict:
    defaults = {"kind": "DEPOSIT"}
    defaults.update(overrides)
    return defaults


def balance_payment_payload(expected_order_version, applied_credit_cents=0, **overrides) -> dict:
    defaults = {
        "kind": "BALANCE",
        "applied_credit_cents": applied_credit_cents,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def slot_payload(fulfillment_mode="PICKUP", route_id=None, window_start_min=None, **overrides) -> dict:
    defaults = {"fulfillment_mode": fulfillment_mode}
    if route_id is not None:
        defaults["route_id"] = route_id
    if window_start_min is not None:
        defaults["window_start_min"] = window_start_min
    defaults.update(overrides)
    return defaults


def commit_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def credit_adjustment_payload(delta_cents, reason="adjustment", **overrides) -> dict:
    defaults = {"delta_cents": delta_cents, "reason": reason}
    defaults.update(overrides)
    return defaults
