"""Payload factories — one per write endpoint, input fields only.

Field names are PRD-exact. Each factory provides sensible defaults and accepts
**overrides for the values a test needs to control.
"""
import itertools

# Monotonic counter so default unique codes/skus/lot_refs don't collide within a test.
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ---- PriceTier ----
def create_price_tier_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("TIER"),
        "discount_bps": 0,
        "min_monthly_kg": 0,
        "freshness_max_days": 60,
    }
    defaults.update(overrides)
    return defaults


# ---- WholesaleAccount ----
def create_account_payload(price_tier_id: str, **overrides) -> dict:
    defaults = {
        "name": "Test Cafe",
        "price_tier_id": price_tier_id,
        "net_terms_days": 30,
        "credit_limit_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


# ---- RoastProfile ----
def create_roast_profile_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Profile",
        "roast_level": "MEDIUM",
        "expected_shrink_bps": 1500,
        "charge_temp_c": 205,
    }
    defaults.update(overrides)
    return defaults


# ---- Product ----
def create_product_payload(roast_profile_id: str, **overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "roast_profile_id": roast_profile_id,
        "base_price_cents_per_kg": 2000,
        "freshness_window_days": 60,
    }
    defaults.update(overrides)
    return defaults


# ---- GreenLot ----
def create_green_lot_payload(**overrides) -> dict:
    defaults = {
        "origin": "Test Origin",
        "lot_ref": _uniq("LOT"),
        "received_kg": 100,
        "par_level_kg": 10,
    }
    defaults.update(overrides)
    return defaults


# ---- RoastBatch ----
def create_roast_batch_payload(green_lot_id: str, product_id: str,
                               expected_green_lot_version, **overrides) -> dict:
    defaults = {
        "green_lot_id": green_lot_id,
        "product_id": product_id,
        "planned_green_kg": 20,
        "expected_green_lot_version": expected_green_lot_version,
    }
    defaults.update(overrides)
    return defaults


def start_roast_batch_payload(actual_green_kg, **overrides) -> dict:
    defaults = {"actual_green_kg": actual_green_kg}
    defaults.update(overrides)
    return defaults


def complete_roast_batch_payload(actual_roasted_kg, **overrides) -> dict:
    defaults = {"actual_roasted_kg": actual_roasted_kg}
    defaults.update(overrides)
    return defaults


# ---- StandingOrder ----
def create_standing_order_payload(product_id: str, next_release_at: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "qty_kg": 5,
        "cadence_days": 7,
        "next_release_at": next_release_at,
    }
    defaults.update(overrides)
    return defaults


# ---- Order ----
def create_order_payload(lines: list, **overrides) -> dict:
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def order_line(product_id: str, qty_kg) -> dict:
    return {"product_id": product_id, "qty_kg": qty_kg}


# ---- Fulfillment ----
def create_fulfillment_payload(product_id: str, roasted_lot_id: str, allocated_kg,
                               expected_roasted_lot_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "roasted_lot_id": roasted_lot_id,
        "allocated_kg": allocated_kg,
        "expected_roasted_lot_version": expected_roasted_lot_version,
    }
    defaults.update(overrides)
    return defaults


# ---- SampleRequest ----
def create_sample_request_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "sample_kg": 0.25,
    }
    defaults.update(overrides)
    return defaults


def review_sample_request_payload(decision: str, cupping_score, **overrides) -> dict:
    defaults = {"decision": decision, "cupping_score": cupping_score}
    defaults.update(overrides)
    return defaults


def convert_sample_request_payload(qty_kg, **overrides) -> dict:
    defaults = {"qty_kg": qty_kg}
    defaults.update(overrides)
    return defaults


# ---- Payment ----
def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


# ---- Clock ----
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
