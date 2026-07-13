"""Payload factories — one per entity, input fields only."""
from .constants import CATALOG_DEFAULTS

_ISBN_SEQ = {"n": 0}


def _next_isbn() -> str:
    """A distinct 13-digit ISBN per call (each test runs on a fresh DB)."""
    _ISBN_SEQ["n"] += 1
    return f"978{_ISBN_SEQ['n']:010d}"


def create_catalog_item_payload(**overrides) -> dict:
    defaults = {
        "isbn13": overrides.pop("isbn13", _next_isbn()),
        "edition": 1,
        "title": "Test Title",
        "author": "Test Author",
        "list_price_cents": CATALOG_DEFAULTS["list_price_cents"],
        "rental_base_cents": CATALOG_DEFAULTS["rental_base_cents"],
        "ebook_price_cents": CATALOG_DEFAULTS["ebook_price_cents"],
        "buyback_base_cents": CATALOG_DEFAULTS["buyback_base_cents"],
        "replacement_fee_cents": CATALOG_DEFAULTS["replacement_fee_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_unit_payload(catalog_item_id, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "condition_grade": "GOOD",
        "acquisition_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "customer@example.com", "full_name": "Test Customer"}
    defaults.update(overrides)
    return defaults


def create_wallet_adjustment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "kind": "TOP_UP"}
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "STUDY",
        "monthly_fee_cents": 1499,
        "rental_discount_pct": 0.05,
        "includes_solutions": False,
        "term_months": 1,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(plan_id, **overrides) -> dict:
    defaults = {"plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(catalog_item_id, fulfillment_type="RENT", **overrides) -> dict:
    """Build an order payload. rental_term_days / desired_start_date only included
    when explicitly supplied (BUY must omit rental_term_days)."""
    payload = {"catalog_item_id": catalog_item_id, "fulfillment_type": fulfillment_type}
    payload.update(overrides)
    return payload


def create_buyback_quote_payload(catalog_item_id, declared_condition, expected_customer_version, **overrides) -> dict:
    defaults = {
        "catalog_item_id": catalog_item_id,
        "declared_condition": declared_condition,
        "expected_customer_version": expected_customer_version,
    }
    defaults.update(overrides)
    return defaults


def inspect_return_payload(reported_condition, highlight_pct_reported=0, is_lost=False, **overrides) -> dict:
    defaults = {
        "reported_condition": reported_condition,
        "highlight_pct_reported": highlight_pct_reported,
        "is_lost": is_lost,
    }
    defaults.update(overrides)
    return defaults


def inspect_buyback_payload(assessed_condition, **overrides) -> dict:
    defaults = {"assessed_condition": assessed_condition}
    defaults.update(overrides)
    return defaults


def respond_revision_payload(action, **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults
