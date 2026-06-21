"""Payload factories — one per entity, input fields only."""
import uuid


# Standard active window used across most tests. The clock is set inside it by fixtures.
DEFAULT_ACTIVE_FROM = "2026-06-01T00:00:00Z"
DEFAULT_ACTIVE_UNTIL = "2026-07-01T00:00:00Z"
DEFAULT_CLOCK = "2026-06-15T00:00:00Z"


def _unique_email(prefix="cust"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _unique_code(prefix="CODE"):
    return f"{prefix}_{uuid.uuid4().hex[:10].upper()}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "display_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(**overrides) -> dict:
    defaults = {
        "code": _unique_code("SEG"),
        "name": "Test Segment",
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(promo_type="PERCENT_OFF", **overrides) -> dict:
    """Base promotion payload. Supply type-specific fields via overrides.

    PERCENT_OFF -> percent_off; BOGO -> bogo_sku; THRESHOLD -> threshold_tiers.
    """
    defaults = {
        "name": "Test Promotion",
        "promo_type": promo_type,
        "stacking_class": "STACKABLE",
        "active_from": DEFAULT_ACTIVE_FROM,
        "active_until": DEFAULT_ACTIVE_UNTIL,
    }
    if promo_type == "PERCENT_OFF":
        defaults["percent_off"] = 0.10
    elif promo_type == "BOGO":
        defaults["bogo_sku"] = "B"
    elif promo_type == "THRESHOLD":
        defaults["threshold_tiers"] = [{"min_subtotal_cents": 0, "discount_cents": 1000}]
    defaults.update(overrides)
    return defaults


def create_coupon_payload(code=None, use_mode="MULTI_USE", **overrides) -> dict:
    defaults = {
        "code": code if code is not None else _unique_code("CPN"),
        "use_mode": use_mode,
    }
    if use_mode == "MULTI_USE" and "max_total_redemptions" not in overrides:
        defaults["max_total_redemptions"] = 100
    defaults.update(overrides)
    return defaults


def create_blackout_payload(starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": "test blackout",
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_rule_payload(promotion_a_id: str, promotion_b_id: str, **overrides) -> dict:
    defaults = {
        "promotion_a_id": promotion_a_id,
        "promotion_b_id": promotion_b_id,
        "note": "no combine",
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_line_payload(sku="A", unit_price_cents=1000, quantity=1, **overrides) -> dict:
    defaults = {
        "sku": sku,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def apply_coupon_payload(code: str, expected_promotion_version=None, **overrides) -> dict:
    defaults = {"code": code}
    if expected_promotion_version is not None:
        defaults["expected_promotion_version"] = expected_promotion_version
    defaults.update(overrides)
    return defaults


def checkout_payload(expected_cart_version: int, **overrides) -> dict:
    defaults = {"expected_cart_version": expected_cart_version}
    defaults.update(overrides)
    return defaults


def set_clock_payload(now_utc=DEFAULT_CLOCK, **overrides) -> dict:
    defaults = {"now_utc": now_utc}
    defaults.update(overrides)
    return defaults


def advance_clock_payload(seconds: int, **overrides) -> dict:
    defaults = {"seconds": seconds}
    defaults.update(overrides)
    return defaults
