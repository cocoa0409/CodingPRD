"""Catalog creation, computed fields, not-found and body-validation corners."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_sku_payload, create_release_payload, create_listing_payload,
    create_account, create_sku, make_seller_headers,
    assert_sku, assert_release,
    NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_sku_returns_201_object_with_default_category(api):
    """PRD §3.1: "Its `release_category` is either `LIMITED`, meaning the model
    is drop-and-raffle gated, or `GENERAL`, meaning it is openly tradable; when
    omitted at creation the category defaults to `GENERAL`."

    Design: Corner/entities/sku_creation_returns_201_with_envelope
    """
    resp = api.create_sku(create_sku_payload(style_code="AA0001-1", name="Test Sku",
                                             brand="Nike", retail_price_cents=20000), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"
    assert data["style_code"] == "AA0001-1"
    assert data["release_category"] == "GENERAL"
    assert_sku(data)


def test_release_available_units_computed_on_create(api):
    """PRD §2.9: "Its `available_units` is always exactly its `allocated_quantity`
    minus its `reserved_units` minus its `sold_units`; this equality is an
    invariant that every release-affecting operation must preserve."

    Design: Corner/entities/release_available_units_computed_on_create
    """
    sku = create_sku(api)
    resp = api.create_release(create_release_payload(sku_id=sku["id"], allocated_quantity=5),
                              ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["available_units"] == 5
    assert data["status"] == "SCHEDULED"
    assert_release(data)


def test_get_nonexistent_account_returns_not_found(api):
    """PRD §2.8: "a missing account yields `ERR_ACCOUNT_NOT_FOUND`".

    Design: Corner/entities/account_get_nonexistent_not_found
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.8: "a missing order yields `ERR_ORDER_NOT_FOUND`".

    Design: Corner/entities/order_get_nonexistent_not_found
    """
    resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_get_nonexistent_listing_returns_not_found(api):
    """PRD §2.8: "a missing listing yields `ERR_LISTING_NOT_FOUND`".

    Design: Corner/entities/listing_get_nonexistent_not_found
    """
    buyer_headers = {"X-User-ID": NON_EXISTENT_UUID, "X-User-Role": "Buyer"}
    resp = api.get_listing(NON_EXISTENT_UUID, buyer_headers)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND.value)


def test_create_sku_missing_brand_returns_validation(api):
    """PRD §3.1: "A `Sku` describes a shoe model and is created with a
    `style_code` (the manufacturer style code), a display `name`, a `brand`, and
    a `retail_price_cents` MSRP that must be greater than zero."
    PRD §2.8: "a missing required field, an invalid enum value, a non-positive
    integer where a positive value is required, or a time window whose start is
    not strictly before its end all yield `ERR_VALIDATION` (422)."

    Design: Corner/entities/sku_create_missing_required_field_returns_validation
    """
    resp = api.create_sku({"style_code": "AA0003-3", "name": "NoBrand",
                           "retail_price_cents": 20000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_listing_invalid_condition_enum_returns_validation(api):
    """PRD §2.8: "a missing required field, an invalid enum value, a non-positive
    integer where a positive value is required, or a time window whose start is
    not strictly before its end all yield `ERR_VALIDATION` (422)."

    Design: Corner/entities/listing_create_invalid_enum_condition_returns_validation
    """
    sku = create_sku(api)
    seller = create_account(api, full_name="Enum Seller")
    payload = create_listing_payload(sku_id=sku["id"], seller_account_id=seller["id"],
                                     condition="MINT")
    resp = api.create_listing(payload, make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_releases_list_is_paginated_and_filterable(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."
    PRD §3.2: "the list view may be narrowed by `sku_id` and by `status`, and
    honors the standard `limit` and `offset` parameters."

    Design: Corner/endpoints/releases_list_is_paginated
    """
    sku = create_sku(api)
    api.create_release(create_release_payload(sku_id=sku["id"], allocated_quantity=4), ADMIN)
    resp = api.list_releases(ADMIN, params={"sku_id": sku["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert all(r["sku_id"] == sku["id"] for r in data)
