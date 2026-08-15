"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import uuid

from .constants import DEFAULT_CUTOFF_MINUTE, TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_customer_payload(**overrides) -> dict:
    """Required: account_number, display_name, credit_limit_cents,
    primary_ship_to_state (PRD §3.1). Optional fields only when overridden."""
    defaults = {
        "account_number": _uniq("ACCT"),
        "display_name": "Test Customer",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "primary_ship_to_state": TEST_DEFAULTS["SHIP_TO_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    """Required: sku, description, item_class, list_price_cents (PRD §3.1)."""
    defaults = {
        "sku": _uniq("SKU"),
        "description": "Test item",
        "item_class": "STOCKED",
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_price_rule_payload(**overrides) -> dict:
    """Exactly one of item_id / item_class must be present (PRD §3.2)."""
    defaults = {
        "customer_tier": "STANDARD",
        "item_class": "STOCKED",
        "rule_type": "DISCOUNT_PCT",
        "discount_pct": 10,
        "effective_from": "2026-01-01",
        "effective_to": "2027-01-01",
    }
    defaults.update(overrides)
    # PRD §3.2: "exactly one of `item_id` ... or `item_class` ... must be set —
    # supplying both or neither is a shape violation". When the caller scopes the
    # rule to an item without explicitly naming item_class, drop the class
    # default so the payload stays PRD-valid. (Callers passing item_class
    # explicitly — e.g. the deliberate both-set shape test — are left alone.)
    if defaults.get("item_id") is not None and "item_class" not in overrides:
        defaults.pop("item_class", None)
    # PRD §3.2: "each must omit the other's value field" — a FIXED_PRICE rule
    # must not carry discount_pct, so drop the default unless the caller set it.
    if defaults.get("rule_type") == "FIXED_PRICE" and "discount_pct" not in overrides:
        defaults.pop("discount_pct", None)
    return defaults


def create_rebate_agreement_payload(**overrides) -> dict:
    """period_start/period_end closed interval; tiers start at threshold 0 (PRD §3.9)."""
    defaults = {
        "period_start": "2026-07-01",
        "period_end": "2026-09-30",
        "tiers": [{"threshold_cents": 0, "rebate_bps": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(**overrides) -> dict:
    """BRANCH locations carry same_day_cutoff_minute; CENTRAL omit it (PRD §3.3)."""
    defaults = {
        "location_code": _uniq("LOC"),
        "location_type": "BRANCH",
        "region_state": "OH",
        "same_day_cutoff_minute": DEFAULT_CUTOFF_MINUTE,
    }
    defaults.update(overrides)
    if defaults.get("location_type") == "CENTRAL":
        defaults.pop("same_day_cutoff_minute", None)
    return defaults


def create_cart_payload(customer_id: str, lines=None, **overrides) -> dict:
    """lines: [{item_id, qty}], at least one line (PRD §3.4)."""
    defaults = {
        "customer_id": customer_id,
        "lines": lines if lines is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(
    customer_id: str, branch_id: str, lines=None, **overrides
) -> dict:
    """Exactly one of lines / source_cart_id must be supplied (PRD §3.5)."""
    defaults = {
        "customer_id": customer_id,
        "fulfillment_branch_id": branch_id,
        "fulfillment_method": "WILL_CALL",
    }
    if lines is not None:
        defaults["lines"] = lines
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id: str, lines, **overrides) -> dict:
    """lines: [{order_line_id, qty, condition}] (PRD §3.8)."""
    defaults = {"order_id": order_id, "lines": lines}
    defaults.update(overrides)
    return defaults
