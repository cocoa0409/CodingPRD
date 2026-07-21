"""Catalog (SKU) and customer creation, validation, computed fields, listing.

Each test translates exactly one corner-design instance (queue B).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_store_payload,
    create_sku_payload,
    create_customer_payload,
    new_store,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["store_staff_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_sku_create_returns_all_fields_and_computed_availability(api):
    """PRD §3.1: "Opening stock may be seeded at creation through
    `initial_on_hand_qty`, which populates `on_hand_qty`; `reserved_qty` starts
    at zero, and the computed `availability_status` is derived immediately as
    described under stock and availability above."
    PRD §2.9: "otherwise the status is `IN_STOCK`."

    Design: Corner/entities/sku_create_returns_all_fields_and_computed_availability
    """
    store = new_store(api)
    resp = api.create_sku(
        create_sku_payload(store["id"], base_price_cents=4000, initial_on_hand_qty=10), STAFF
    )
    data = validate_success(resp, 201)
    assert data["availability_status"] == "IN_STOCK"
    assert data["reserved_qty"] == 0
    assert data["version"] == 1


def test_sku_get_nonexistent_returns_not_found(api):
    """PRD §2.7: "Each missing reference has its own error: a missing store
    yields `ERR_STORE_NOT_FOUND`, a missing customer `ERR_CUSTOMER_NOT_FOUND`, a
    missing SKU `ERR_SKU_NOT_FOUND`, a missing registry `ERR_REGISTRY_NOT_FOUND`,
    a missing registry item `ERR_REGISTRY_ITEM_NOT_FOUND`, a missing order
    `ERR_ORDER_NOT_FOUND`, a missing shelf `ERR_SHELF_NOT_FOUND`, a missing
    consignment item `ERR_CONSIGNMENT_ITEM_NOT_FOUND`, a missing trade-in
    `ERR_TRADE_IN_NOT_FOUND`, and a missing special order
    `ERR_SPECIAL_ORDER_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/sku_get_nonexistent_returns_not_found
    """
    resp = api.get_sku(NON_EXISTENT_UUID, ANON)
    validate_error(resp, ApiErrorId.ERR_SKU_NOT_FOUND.value)


def test_sku_create_missing_required_field_returns_validation(api):
    """PRD §2.8: "Body well-formedness follows — required fields present, enum
    values in range, integers non-negative — reported as `ERR_VALIDATION`
    (HTTP 422), and alongside it the order-specific structural checks
    (`ERR_EMPTY_ORDER`, `ERR_INVALID_PICKUP_WINDOW`)."

    Design: Corner/entities/sku_create_missing_required_field_returns_validation
    """
    store = new_store(api)
    payload = create_sku_payload(store["id"])
    payload.pop("base_price_cents")
    resp = api.create_sku(payload, STAFF)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_store_create_defaults_applied_when_omitted(api):
    """PRD §3.1: "A store carries a display `name` and a two-letter US
    `state_code` (for example, CA), and it defines its own trading day:
    `open_minute` and `close_minute` express the daily opening and closing times
    as minutes elapsed from local midnight, defaulting to 540 (nine in the
    morning) and 1200 (eight in the evening) respectively."
    PRD §3.1: "A store also declares how many manned pickup counters it runs
    through `pickup_station_count`, which defaults to 2; valid station indices
    run from 1 up to that count."

    Design: Corner/entities/store_create_defaults_applied_when_omitted
    """
    resp = api.create_store(create_store_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert data["open_minute"] == 540
    assert data["close_minute"] == 1200
    assert data["pickup_station_count"] == 2


def test_sku_create_invalid_enum_category_returns_validation(api):
    """PRD §2.8: "Body well-formedness follows — required fields present, enum
    values in range, integers non-negative — reported as `ERR_VALIDATION`
    (HTTP 422), and alongside it the order-specific structural checks
    (`ERR_EMPTY_ORDER`, `ERR_INVALID_PICKUP_WINDOW`)."
    PRD §3.1: "A SKU records the owning `store_id`, a human catalog code
    `sku_code`, a product `name`, a `category` — one of `CLOTHING`, `GEAR`,
    `TOY`, `FEEDING`, or `NURSERY` — and a `size_stage` drawn from the
    developmental ladder `NEWBORN`, `M0_3`, `M3_6`, `M6_12`, `M12_24`, `T2`,
    `T3`, and `T4`."

    Design: Corner/entities/sku_create_invalid_enum_category_returns_validation
    """
    store = new_store(api)
    resp = api.create_sku(
        create_sku_payload(store["id"], category="SPACESHIP", base_price_cents=4000), STAFF
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_customer_loyalty_tier_computed_from_seed_lifetime_spend(api):
    """PRD §3.5: "a customer is `PLATINUM` once lifetime spend reaches at least
    400000 cents, otherwise `GOLD` at 150000 cents or more, otherwise `SILVER`
    at 50000 cents or more, and otherwise `BRONZE`."
    PRD §3.5: "A customer's wallet and loyalty history may be seeded at
    registration: `initial_lifetime_spend_cents` seeds `lifetime_spend_cents`,
    `initial_store_credit_cents` seeds `store_credit_balance_cents`, and
    `initial_loyalty_points` seeds `loyalty_points`; each seeded field otherwise
    starts at zero."
    PRD §3.5: "The `loyalty_tier` is always a pure function of
    `lifetime_spend_cents` and is computed immediately, including at
    registration."

    Design: Corner/entities/customer_loyalty_tier_computed_from_seed_lifetime_spend
    """
    resp = api.create_customer(
        create_customer_payload(initial_lifetime_spend_cents=60000), ANON
    )
    data = validate_success(resp, 201)
    assert data["loyalty_tier"] == "SILVER"
    assert data["loyalty_points"] == 0


def test_skus_list_returns_pagination_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`
    (the number of matching records before pagination), and `has_more` (true
    when records remain beyond the current page) inside the `meta` object."

    Design: Corner/entities/skus_list_returns_pagination_envelope
    """
    store = new_store(api)
    get_success_data(
        api.create_sku(create_sku_payload(store["id"], initial_on_hand_qty=10), STAFF)
    )
    resp = api.list_skus(ANON, params={"store_id": store["id"]})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] >= 1


def test_sku_availability_low_stock_at_threshold_three(api):
    """PRD §2.9: "Availability is recomputed on every change to either quantity
    and drives the computed `availability_status`: when available is zero or
    below, the status is `OUT_OF_STOCK`; when available is greater than zero but
    no more than the low-stock threshold of 3 units, the status is `LOW_STOCK`;
    otherwise the status is `IN_STOCK`."

    Design: Corner/calculations/sku_availability_low_stock_at_threshold_three
    """
    store = new_store(api)
    data = validate_success(
        api.create_sku(create_sku_payload(store["id"], initial_on_hand_qty=3), STAFF), 201
    )
    assert data["availability_status"] == "LOW_STOCK"


def test_restock_increments_on_hand_and_recomputes_availability(api):
    """PRD §3.1: "Store staff add physical units later by restocking a SKU with
    an `add_qty` that is added to `on_hand_qty`; availability is recomputed, and
    — because freed or added stock can satisfy a waiting customer — the restock
    cascades into the special-order waitlist, promoting the earliest waiting
    request for that SKU as described in the special-order workflow."
    PRD §2.9: "when available is zero or below, the status is `OUT_OF_STOCK`;
    when available is greater than zero but no more than the low-stock threshold
    of 3 units, the status is `LOW_STOCK`; otherwise the status is `IN_STOCK`."

    Design: Corner/endpoints/restock_increments_on_hand_and_recomputes_availability
    """
    store = new_store(api)
    sku = validate_success(
        api.create_sku(create_sku_payload(store["id"], initial_on_hand_qty=0), STAFF), 201
    )
    assert sku["availability_status"] == "OUT_OF_STOCK"
    data = validate_success(api.restock_sku(sku["id"], {"add_qty": 10}, STAFF), 200)
    assert data["on_hand_qty"] == 10
    assert data["availability_status"] == "IN_STOCK"
