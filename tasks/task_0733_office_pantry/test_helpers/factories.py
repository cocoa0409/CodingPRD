"""Payload factories — one per entity, input fields only."""


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "STARTER",
        "billing_type": "FLAT",
        "base_fee_cents": 0,
        "per_employee_fee_cents": 0,
        "flat_fee_cents": 1000,
        "volume_discount_threshold_headcount": 50,
        "volume_discount_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Client",
        "headcount": 5,
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Location",
        "kind": "PANTRY",
        "capacity_units": 20,
        "service_fee_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "SKU-TEST",
        "name": "Test Product",
        "category": "SNACK",
        "dietary_flags": [],
        "unit_cost_cents": 100,
        "requires_refrigeration": False,
    }
    defaults.update(overrides)
    return defaults


def create_preference_payload(**overrides) -> dict:
    defaults = {
        "dietary_flag": "CONTAINS_NUTS",
    }
    defaults.update(overrides)
    return defaults


def create_par_level_payload(product_id: str, par_units: int = 1, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "par_units": par_units,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(plan_id: str, expected_client_version: int, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "expected_client_version": expected_client_version,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(location_id: str, scheduled_at: str, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "scheduled_at": scheduled_at,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(dispute_reason: str = "short-shipped", **overrides) -> dict:
    defaults = {"dispute_reason": dispute_reason}
    defaults.update(overrides)
    return defaults


def create_feedback_payload(product_id: str, rating: int = 3, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "rating": rating,
    }
    defaults.update(overrides)
    return defaults


def create_headcount_patch_payload(headcount: int) -> dict:
    return {"headcount": headcount}


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
