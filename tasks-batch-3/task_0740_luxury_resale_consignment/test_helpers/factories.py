"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "SELLER_NAME": "S1",
    "SELLER_EMAIL": "s1@x.com",
    "BUYER_NAME": "B1",
    "BUYER_EMAIL": "b1@x.com",
    "BRAND": "TestBrand",
    "TITLE": "Test Item",
    "DECLARED_VALUE_CENTS": 100000,
    "LIST_PRICE_CENTS": 200000,
    "CONCIERGE_NAME": "C1",
    "REGION": "NYC",
    "PLATE": "V1",
}

# Baseline HANDBAGS policy used across most setups (PRD §3.1).
HANDBAGS_POLICY = {
    "category": "HANDBAGS",
    "base_commission_pct": 0.20,
    "buyer_fee_pct": 0.10,
    "buyer_fee_flat_cents": 500,
    "return_window_days": 14,
    "min_offer_pct": 0.70,
    "listable_min_condition_grade": "C",
    "pickup_insurance_cap_cents": 5000000,
}


def create_seller_payload(**overrides) -> dict:
    defaults = {"display_name": DEFAULTS["SELLER_NAME"], "email": DEFAULTS["SELLER_EMAIL"]}
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> dict:
    defaults = {"display_name": DEFAULTS["BUYER_NAME"], "email": DEFAULTS["BUYER_EMAIL"]}
    defaults.update(overrides)
    return defaults


def create_category_policy_payload(**overrides) -> dict:
    defaults = dict(HANDBAGS_POLICY)
    defaults.update(overrides)
    return defaults


def create_item_payload(seller_id: str, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "category": "HANDBAGS",
        "brand": DEFAULTS["BRAND"],
        "title": DEFAULTS["TITLE"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
        "intake_channel": "DROP_OFF",
    }
    defaults.update(overrides)
    return defaults


def create_authenticate_payload(verdict: str = "AUTHENTIC", condition_grade: str = "A", **overrides) -> dict:
    defaults = {"verdict": verdict, "condition_grade": condition_grade}
    defaults.update(overrides)
    return defaults


def create_listing_payload(item_id: str, list_price_cents: int = None, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "list_price_cents": list_price_cents if list_price_cents is not None else DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(listing_id: str, buyer_id: str, amount_cents: int,
                         expected_listing_version: int, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "amount_cents": amount_cents,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(counter_amount_cents: int, **overrides) -> dict:
    defaults = {"counter_amount_cents": counter_amount_cents}
    defaults.update(overrides)
    return defaults


def create_sale_payload(listing_id: str, buyer_id: str, **overrides) -> dict:
    defaults = {"listing_id": listing_id, "buyer_id": buyer_id}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(sale_id: str, type: str, reason: str = "reason", **overrides) -> dict:
    defaults = {"sale_id": sale_id, "type": type, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_resolve_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_concierge_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["CONCIERGE_NAME"], "region": DEFAULTS["REGION"]}
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {"plate": DEFAULTS["PLATE"]}
    defaults.update(overrides)
    return defaults


def create_pickup_payload(item_id: str, concierge_id: str, vehicle_id: str,
                          window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "concierge_id": concierge_id,
        "vehicle_id": vehicle_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults
