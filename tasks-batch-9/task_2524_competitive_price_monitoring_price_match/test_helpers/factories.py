"""Payload factories — one per resource, client-supplied input fields only."""

DEFAULTS = {
    "MARKET_CODE": "US-WEST",
    "MARKET_NAME": "US West",
    "STRATEGIC_INDEX_TARGET_BP": 9800,
    "INDEX_TOLERANCE_BP": 150,
    "COMPETITOR_CODE": "C-ALPHA",
    "COMPETITOR_NAME": "Alpha Mart",
    "SKU": "SKU-APPL-1",
    "CATEGORY_CODE": "APPLIANCE",
    "BRAND": "Vitala",
    "STORE_CODE": "STORE-101",
    "COMPETITOR_IDENTIFIER": "00712345678905",
    "CLOCK": "2026-08-01T00:00:00Z",
}


def create_market_payload(**overrides) -> dict:
    payload = {
        "market_code": DEFAULTS["MARKET_CODE"],
        "name": DEFAULTS["MARKET_NAME"],
        "strategic_positioning": "AT_PARITY",
        "strategic_index_target_bp": DEFAULTS["STRATEGIC_INDEX_TARGET_BP"],
        "index_tolerance_bp": DEFAULTS["INDEX_TOLERANCE_BP"],
    }
    payload.update(overrides)
    return payload


def create_competitor_payload(market_id: str, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "competitor_code": DEFAULTS["COMPETITOR_CODE"],
        "name": DEFAULTS["COMPETITOR_NAME"],
        "collection_method": "ONLINE",
        "tier": "PRIMARY",
    }
    payload.update(overrides)
    return payload


def create_product_payload(market_id: str, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "sku": DEFAULTS["SKU"],
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "brand": DEFAULTS["BRAND"],
        "own_price_cents": 12999,
        "unit_cost_cents": 7000,
        "margin_floor_pct": 0.20,
        "map_floor_cents": 0,
        "index_weight_bp": 10000,
    }
    payload.update(overrides)
    return payload


def create_store_payload(market_id: str, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "store_code": DEFAULTS["STORE_CODE"],
        "override_authority_cents": 5000,
        "label_printer_capacity_per_day": 5,
    }
    payload.update(overrides)
    return payload


def create_match_payload(product_id: str, competitor_id: str, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "competitor_id": competitor_id,
        "match_method": "IDENTIFIER",
        "identifier_score": 95,
        "attribute_score": 95,
        "image_score": 95,
        "competitor_identifier": DEFAULTS["COMPETITOR_IDENTIFIER"],
    }
    payload.update(overrides)
    return payload


def create_observation_payload(link_id: str, **overrides) -> dict:
    payload = {
        "link_id": link_id,
        "observed_price_cents": 12000,
        "collection_method": "ONLINE",
        "observed_at": "2026-07-31T18:00:00Z",
        "in_stock": True,
    }
    payload.update(overrides)
    return payload


def create_index_report_payload(market_id: str, expected_market_version: int, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "basis": "MATCHED_BASKET",
        "expected_market_version": expected_market_version,
    }
    payload.update(overrides)
    return payload


def create_repricing_rule_payload(market_id: str, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "target_position_bp": 9700,
        "max_change_pct": 0.10,
        "change_frequency_limit_days": 0,
        "priority": 10,
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(product_id: str, expected_product_version: int, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "origin": "MANUAL",
        "requested_price_cents": 12000,
        "effective_from": DEFAULTS["CLOCK"],
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def create_match_policy_payload(market_id: str, **overrides) -> dict:
    payload = {
        "market_id": market_id,
        "eligible_competitor_tiers": ["PRIMARY"],
        "daily_override_budget_cents": 100000,
        "max_match_discount_pct": 0.30,
        "claim_window_hours": 168,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id, product_id, competitor_id, store_id, **overrides) -> dict:
    payload = {
        "policy_id": policy_id,
        "product_id": product_id,
        "competitor_id": competitor_id,
        "store_id": store_id,
        "claimed_price_cents": 10400,
        "claimed_observed_at": "2026-07-31T18:00:00Z",
        "competitor_evidence_ref": "receipt-1",
    }
    payload.update(overrides)
    return payload


def create_label_batch_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "window_start": "2026-08-01T08:00:00Z",
        "window_end": "2026-08-01T09:00:00Z",
        "reserved_item_count": 0,
    }
    payload.update(overrides)
    return payload
