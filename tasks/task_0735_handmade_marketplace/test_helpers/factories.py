"""Payload factories — one per entity, input fields only.

Each factory produces a minimal valid create payload with sensible defaults, then
applies **overrides. Only fields the buyer/seller/admin supplies (source: input)
appear here; server-managed and computed fields are never sent.
"""

DEFAULTS = {
    "OWNER_SELLER_ID": "seller_1",
    "SHOP_NAME": "Handmade Co",
    "PROFILE_NAME": "US",
    "MATERIAL_NAME": "Material",
    "LISTING_TITLE": "Handmade Item",
    "PRICE_CENTS": 2000,
    "PROCESSING_DAYS": 1,
    "QUANTITY": 10,
}


def create_shop_payload(**overrides) -> dict:
    payload = {
        "owner_seller_id": DEFAULTS["OWNER_SELLER_ID"],
        "name": DEFAULTS["SHOP_NAME"],
    }
    payload.update(overrides)
    return payload


def create_shipping_profile_payload(shop_id, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "name": DEFAULTS["PROFILE_NAME"],
        "base_cost_cents": 0,
        "per_item_cost_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_material_payload(shop_id, stock_qty, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "name": DEFAULTS["MATERIAL_NAME"],
        "stock_qty": stock_qty,
    }
    payload.update(overrides)
    return payload


def create_listing_payload(shop_id, shipping_profile_id,
                           fulfillment_type="READY_TO_SHIP", **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "shipping_profile_id": shipping_profile_id,
        "title": DEFAULTS["LISTING_TITLE"],
        "fulfillment_type": fulfillment_type,
        "processing_time_days": DEFAULTS["PROCESSING_DAYS"],
        "price_cents": DEFAULTS["PRICE_CENTS"],
    }
    if fulfillment_type == "READY_TO_SHIP":
        payload["quantity"] = DEFAULTS["QUANTITY"]
    payload.update(overrides)
    return payload


def create_vacation_period_payload(shop_id, starts_at, ends_at, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def create_order_payload(shop_id, listing_id, quantity=1, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "listing_id": listing_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def create_review_payload(order_id, rating, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "rating": rating,
    }
    payload.update(overrides)
    return payload


def create_case_payload(order_id, case_type="NON_DELIVERY", **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "type": case_type,
    }
    payload.update(overrides)
    return payload


def create_payout_payload(shop_id, expected_shop_version, **overrides) -> dict:
    payload = {
        "shop_id": shop_id,
        "expected_shop_version": expected_shop_version,
    }
    payload.update(overrides)
    return payload
