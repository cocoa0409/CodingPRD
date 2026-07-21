"""Payload factories — one per create endpoint, input fields only.

Each factory returns a fresh dict so overrides never bleed across tests. The
server is restarted (empty DB) before every test, so the module-level unique
counter resets each run — no cross-test collisions.
"""
import itertools

_email_counter = itertools.count(10000)


def fresh_email(prefix: str = "cust") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ---- Customer ----
def create_customer_payload(**overrides) -> dict:
    defaults = {"email": fresh_email(), "full_name": "Test Shopper"}
    defaults.update(overrides)
    return defaults


# ---- Product ----
def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Product",
        "category": "MATERNITY",
        "buy_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


# ---- ProductVariant (product_id supplied in path) ----
def create_variant_payload(**overrides) -> dict:
    defaults = {
        "size_label": "M",
        "trimester_fit": [2],
    }
    defaults.update(overrides)
    return defaults


# ---- FitProfile ----
def create_fit_profile_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "bust_cm": 90,
        "waist_cm": 80,
        "hip_cm": 100,
        "pre_pregnancy_size": "M",
    }
    defaults.update(overrides)
    return defaults


# ---- Order ----
def create_order_payload(customer_id, variant_id, order_type, expected_variant_version,
                         **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "variant_id": variant_id,
        "order_type": order_type,
        "expected_variant_version": expected_variant_version,
    }
    defaults.update(overrides)
    return defaults


# ---- Loyalty adjustment ----
def create_loyalty_adjustment_payload(points_delta, **overrides) -> dict:
    defaults = {"points_delta": points_delta}
    defaults.update(overrides)
    return defaults


# ---- Subscription ----
def create_subscription_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_tier": "CAPSULE_BASIC",
        "monthly_fee_cents": 3000,
        "next_ship_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---- Capsule (subscription_id supplied in path) ----
def create_capsule_payload(item_variant_ids, ship_date="2026-08-01T00:00:00Z",
                           **overrides) -> dict:
    defaults = {"item_variant_ids": item_variant_ids, "ship_date": ship_date}
    defaults.update(overrides)
    return defaults


# ---- Return ----
def create_return_payload(order_id, return_type="REFUND", reason="size", **overrides) -> dict:
    defaults = {"order_id": order_id, "reason": reason, "return_type": return_type}
    defaults.update(overrides)
    return defaults


# ---- Pay ----
def pay_payload(expected_customer_version, redeemed_points=0, **overrides) -> dict:
    defaults = {
        "expected_customer_version": expected_customer_version,
        "redeemed_points": redeemed_points,
    }
    defaults.update(overrides)
    return defaults
