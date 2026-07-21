"""Catalog & registration: customer defaults, required fields, variant sizing,
not-found, catalog filtering, and list-envelope pagination.

Queue B (Corner) — section entities & endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    register_customer_payload, create_variant_payload,
    make_anonymous_headers,
    create_product,
    MISSING_UUID,
)

SM = TEST_USERS["store_manager_headers"]
ANON = make_anonymous_headers()


def test_register_returns_201_with_baseline_ledger_defaults(api):
    """PRD §3.1: "A freshly registered customer is initialized with every ledger
    field at its baseline: `loyalty_points_balance` and `loyalty_lifetime_points` at
    0, `loyalty_tier` at `STANDARD`, `wallet_credit_cents` at 0, `no_show_count` at
    0, `booking_status` at `ACTIVE`, and `account_status` at `ACTIVE`."

    Design: Corner/entities/customer_register_returns_201_with_defaults
    """
    resp = api.register_customer(
        register_customer_payload(email="new-defaults@x.com", full_name="New Person", size_code=22),
        ANON,
    )
    data = validate_success(resp, expected_status=201)
    assert data["loyalty_tier"] == "STANDARD"
    assert data["loyalty_points_balance"] == 0
    assert data["loyalty_lifetime_points"] == 0
    assert data["wallet_credit_cents"] == 0
    assert data["no_show_count"] == 0
    assert data["booking_status"] == "ACTIVE"
    assert data["account_status"] == "ACTIVE"


def test_register_missing_required_size_code_returns_validation(api):
    """PRD §2.9: "a request whose body is malformed, omits a required field, or
    supplies a value of the wrong type is rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/register_missing_required_size_returns_400
    """
    payload = {"email": "bad@x.com", "full_name": "No Size"}
    resp = api.register_customer(payload, ANON)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_variant_size_outside_product_band_rejected(api):
    """PRD §3.2: "a variant whose size falls outside that band is rejected with
    `ERR_SIZE_OUT_OF_RANGE`."

    Design: Corner/entities/variant_create_out_of_size_range_returns_409
    """
    product = create_product(api, size_min=10, size_max=34)
    resp = api.create_variant(
        product["id"], create_variant_payload(size_code=40, color="Navy", inventory_on_hand=5), SM
    )
    validate_error(resp, ApiErrorId.ERR_SIZE_OUT_OF_RANGE.value)


def test_new_variant_computes_available_and_reserved(api):
    """PRD §3.2: "A new variant begins with `inventory_reserved` at 0 and
    `inventory_available` equal to its `inventory_on_hand`, and its `status` is
    `ACTIVE`, the only variant status in this version."

    Design: Corner/entities/variant_create_computes_available_and_reserved
    """
    product = create_product(api)
    resp = api.create_variant(
        product["id"], create_variant_payload(size_code=22, color="Navy", inventory_on_hand=5), SM
    )
    data = validate_success(resp, expected_status=201)
    assert data["inventory_reserved"] == 0
    assert data["inventory_available"] == 5


def test_get_nonexistent_product_returns_not_found(api):
    """PRD §2.10: "the server validates identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` at the first path segment that does not resolve to
    an existing resource, before evaluating any deeper segment or applying business
    rules."

    Design: Corner/entities/product_get_nonexistent_returns_not_found
    """
    resp = api.get_product(MISSING_UUID, ANON)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_product_listing_filters_by_adaptive_feature(api):
    """PRD §3.2: "`adaptive_feature` restricts results to garments whose
    `adaptive_features` include the requested feature".

    Design: Corner/entities/product_filter_by_adaptive_feature
    """
    magnetic = create_product(
        api, name="Magnetic Blouse", category="TOPS", base_price_cents=5000,
        adaptive_features=["MAGNETIC_CLOSURE"],
    )
    plain = create_product(api, name="Plain Tee", category="TOPS", base_price_cents=4000)
    resp = api.list_products(ANON, params={"adaptive_feature": "MAGNETIC_CLOSURE"})
    data, _meta = validate_paginated(resp)
    ids = {p["id"] for p in data}
    assert magnetic["id"] in ids, "magnetic product must appear in filtered results"
    assert plain["id"] not in ids, "plain product must be excluded by the filter"


def test_product_listing_returns_array_envelope_with_pagination(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    size of the full unpaginated result set and `has_more` indicates whether items
    remain beyond the current page."

    Design: Corner/endpoints/products_list_returns_array_envelope_with_pagination
    """
    create_product(api)
    resp = api.list_products(ANON)
    assert resp.json()["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert "total_count" in meta
    assert "has_more" in meta
