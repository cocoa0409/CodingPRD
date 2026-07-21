"""Catalog creation defaults, computed fields, access control, and listing.

Translates queue-B (corner) instances covering entity creation, computed pricing,
tier derivation, RBAC, existence/auth validation, and pagination.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    get_success_data,
    assert_customer, assert_sku, assert_product,
    create_customer_payload, create_product_payload, create_sku_payload,
    create_order_payload, create_order_line_payload,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    make_customer_headers,
    new_customer, new_product,
)

SM = TEST_USERS["store_manager_headers"]


def test_customer_create_defaults_bronze_zero_balances(api):
    """PRD §3.1: "A new customer opens with loyalty_points of 0, store_credit_cents
    of 0, and a loyalty_tier of BRONZE."

    Design: Corner/entities/customer_create_success_defaults
    """
    res = api.create_customer(create_customer_payload(full_name="New Cust"), SM)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["loyalty_tier"] == "BRONZE", cust
    assert cust["loyalty_points"] == 0
    assert cust["store_credit_cents"] == 0


def test_sku_extended_band_size_surcharge(api):
    """PRD §3.1: "the price is the parent product's base_price_cents plus an
    extended-size surcharge of 500 cents whenever the SKU is an extended size"
    PRD §3.1: "A SKU counts as an extended size when its band_size is 40 or greater,
    or when its cup letter is F or larger (that is, F, G, or H)."

    Design: Corner/entities/sku_price_extended_size_surcharge
    """
    prod = new_product(style_name="Ext Bra", brand="Elomi", base_price_cents=4000)
    res = api.create_sku(
        create_sku_payload(prod["id"], band_size=40, cup_size="C", initial_stock=2), SM
    )
    sku = validate_success(res, 201)
    assert_sku(sku)
    assert sku["price_cents"] == 4500, sku


def test_product_is_mastectomy_computed_true(api):
    """PRD §3.1: "The system computes is_mastectomy as true exactly when category
    equals MASTECTOMY_BRA; this flag gates insurance eligibility later."

    Design: Corner/entities/product_is_mastectomy_computed
    """
    res = api.create_product(
        create_product_payload(
            style_name="Mast Bra", brand="Amoena", category="MASTECTOMY_BRA",
            base_price_cents=12000, hygiene_class="INTIMATE_NON_RETURNABLE",
        ),
        SM,
    )
    prod = validate_success(res, 201)
    assert_product(prod)
    assert prod["is_mastectomy"] is True, prod


def test_sku_stock_status_low_at_threshold(api):
    """PRD §2.6: "When available_units is greater than zero but no greater than the
    low-stock threshold of 3 units, stock_status is LOW_STOCK."
    PRD §2.6: "available_units of precisely 3 is LOW_STOCK, and available_units of
    precisely 0 is OUT_OF_STOCK."

    Design: Corner/calculations/stock_status_low_stock_at_threshold
    """
    prod = new_product(base_price_cents=2000)
    res = api.create_sku(create_sku_payload(prod["id"], band_size=34, cup_size="C", initial_stock=3), SM)
    sku = validate_success(res, 201)
    assert sku["available_units"] == 3, sku
    assert sku["stock_status"] == "LOW_STOCK", sku


def test_customer_loyalty_tier_silver_at_1000(api):
    """PRD §3.1: "a balance of 1000 points or more (but below 5000) is SILVER, and
    a balance of 5000 points or more is GOLD (both thresholds are inclusive lower
    bounds, so exactly 1000 is SILVER and exactly 5000 is GOLD)."

    Design: Corner/entities/customer_loyalty_tier_silver_boundary
    """
    cust = new_customer(points=1000)
    refreshed = validate_success(api.get_customer(cust["id"], SM), 200)
    assert refreshed["loyalty_points"] == 1000
    assert refreshed["loyalty_tier"] == "SILVER", refreshed


def test_get_nonexistent_appointment_not_found(api):
    """PRD §2.9: "every resource id named in the path ... must resolve to a real
    resource; path ids are validated left to right, and the first unresolved id
    determines which not-found error is returned (ERR_CUSTOMER_NOT_FOUND, ...,
    ERR_APPOINTMENT_NOT_FOUND, ...)."

    Design: Corner/entities/appointment_get_nonexistent_returns_not_found
    """
    res = api.get_appointment(NON_EXISTENT_UUID, SM)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND)


def test_create_order_missing_customer_id_validation(api):
    """PRD §2.9: "Fifth is body well-formedness — required fields present, enum
    values legal, and numeric ranges honored — reported as ERR_VALIDATION."

    Design: Corner/entities/create_order_missing_required_customer_id_returns_validation
    """
    res = api.create_order({}, TEST_USERS["customer_headers"])
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_customer(create_customer_payload(), headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_customer_cannot_create_product_forbidden(api):
    """PRD §2.1: "When an authenticated user attempts an operation their role is not
    permitted to perform, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/customer_cannot_create_product_returns_forbidden_role
    """
    res = api.create_product(
        create_product_payload(style_name="X Bra", brand="X", base_price_cents=1000),
        TEST_USERS["customer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_other_customer_cannot_cancel_foreign_order(api):
    """PRD §2.1: "ownership checks on any resource that references a customer compare
    the resource's customer_id to X-User-ID, and a mismatch is rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/other_customer_cannot_cancel_foreign_order_returns_not_owner
    """
    cust_a = new_customer(full_name="Cust A")
    cust_b = new_customer(full_name="Cust B")
    order = get_success_data(
        api.create_order(create_order_payload(cust_a["id"]), make_customer_headers(cust_a["id"]))
    )
    res = api.cancel_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_add_line_to_nonexistent_order_not_found(api):
    """PRD §2.9: "every resource id named in the path, and every foreign-key id in
    the body, must resolve to a real resource; path ids are validated left to right,
    and the first unresolved id determines which not-found error is returned
    (... ERR_ORDER_NOT_FOUND ...)."

    Design: Corner/validations/measurement_valid_but_line_left_to_right_existence
    """
    prod = new_product(base_price_cents=2000)
    sku = get_success_data(api.create_sku(create_sku_payload(prod["id"], initial_stock=5), SM))
    res = api.add_order_line(
        NON_EXISTENT_UUID, create_order_line_payload(sku["id"], 1),
        TEST_USERS["customer_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_list_orders_pagination_has_more(api):
    """PRD §2.3: "Every list response carries the pagination fields limit, offset,
    total_count, and has_more inside the meta object of the envelope."

    Design: Corner/endpoints/list_orders_pagination_has_more
    """
    cust = new_customer()
    for _ in range(2):
        get_success_data(
            api.create_order(create_order_payload(cust["id"]), make_customer_headers(cust["id"]))
        )
    data, meta = validate_paginated(api.list_orders(SM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_skus_returns_created_for_product(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return
    resources sorted by their created_at timestamp in ascending order."

    Design: Corner/endpoints/filtered_list_skus_by_product_fk_reverse
    """
    prod = new_product(base_price_cents=2000)
    get_success_data(api.create_sku(create_sku_payload(prod["id"], band_size=34, initial_stock=2), SM))
    get_success_data(api.create_sku(create_sku_payload(prod["id"], band_size=36, initial_stock=2), SM))
    data, _meta = validate_paginated(api.list_skus(SM, params={"product_id": prod["id"]}))
    assert len(data) == 2, data
