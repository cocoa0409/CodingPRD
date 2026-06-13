"""Corner breadth tests — entities section: creation defaults, not-found, required
fields, type/enum constraints, uniqueness, body-FK existence, listing, immutability.

Translates queue-B corner instances under section `entities`.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_customer,
    create_quoted_custom_order,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
)
from test_helpers.factories import (
    create_customer_payload,
    create_inventory_item_payload,
    create_custom_order_payload,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_create_customer_returns_201_with_defaults(api):
    """PRD §3.1: "On creation the customer's `status` is `ACTIVE` and the computed
    `store_credit_balance_cents` is 0."
    PRD §2.4: "`version` is an integer that begins at 1 on creation".

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    res = api.create_customer(
        create_customer_payload(full_name="Ann Beryl", email="ann.create@x.com", phone="555-1001"),
        SA,
    )
    customer = validate_success(res, 201)
    assert customer["status"] == "ACTIVE"
    assert customer["store_credit_balance_cents"] == 0
    assert customer["version"] == 1


def test_get_customer_not_found_returns_404(api):
    """PRD §2.5: "that identifier is resolved first; if it names no existing record, the
    request fails with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer(NON_EXISTENT_UUID, SA)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_create_inventory_item_missing_required_returns_invalid_request(api):
    """PRD §3.1: "An item is created with a `sku` (unique across all items), a `title` such
    as a display name, a `metal_karat` of `K14`, `K18`, or `K24`, and a `list_price_cents`
    that must be greater than 0."
    PRD §2.8: "then request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422 — required
    fields present, enum values legal, integers within their declared ranges)".

    Design: Corner/entities/create_inventory_item_missing_required_returns_invalid_request
    """
    payload = create_inventory_item_payload(sku="NO-PRICE", title="Ring", metal_karat="K18")
    del payload["list_price_cents"]
    res = api.create_inventory_item(payload, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_create_inventory_item_invalid_enum_karat_returns_invalid_request(api):
    """PRD §3.1: "a `metal_karat` of `K14`, `K18`, or `K24`".
    PRD §2.8: "then request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422 — required
    fields present, enum values legal, integers within their declared ranges)".

    Design: Corner/entities/create_inventory_item_invalid_enum_karat_returns_invalid_request
    """
    res = api.create_inventory_item(
        create_inventory_item_payload(sku="BAD-K", title="Ring", metal_karat="K10",
                                      list_price_cents=100000),
        SM,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_duplicate_customer_email_returns_409(api):
    """PRD §2.8: "Two uniqueness constraints exist: a `Customer`'s `email` is unique across
    all customers, and an `InventoryItem`'s `sku` is unique across all inventory items."
    PRD §2.8: "A second customer created with an email already on file, or a second item with
    an existing SKU, is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_customer_email_returns_409
    """
    validate_success(
        api.create_customer(
            create_customer_payload(full_name="First Dup", email="dup@x.com", phone="555-1002"), SA
        ),
        201,
    )
    res = api.create_customer(
        create_customer_payload(full_name="Second Dup", email="dup@x.com", phone="555-1003"), SA
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE.value, expected_status=409)


def test_duplicate_inventory_sku_returns_409(api):
    """PRD §2.8: "Two uniqueness constraints exist: a `Customer`'s `email` is unique across
    all customers, and an `InventoryItem`'s `sku` is unique across all inventory items."
    PRD §2.8: "A second customer created with an email already on file, or a second item with
    an existing SKU, is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_inventory_sku_returns_409
    """
    validate_success(
        api.create_inventory_item(
            create_inventory_item_payload(sku="SKU-DUP", title="A", metal_karat="K14",
                                          list_price_cents=100000),
            SM,
        ),
        201,
    )
    res = api.create_inventory_item(
        create_inventory_item_payload(sku="SKU-DUP", title="B", metal_karat="K14",
                                      list_price_cents=200000),
        SM,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE.value, expected_status=409)


def test_create_custom_order_unknown_customer_returns_fk_not_found(api):
    """PRD §2.5: "When a body foreign key points at a record that does not exist, the request
    fails with `ERR_FK_NOT_FOUND` (HTTP 404). This referential check applies to creating
    custom orders..."

    Design: Corner/entities/create_custom_order_unknown_customer_returns_fk_not_found
    """
    res = api.create_custom_order(
        create_custom_order_payload(NON_EXISTENT_UUID, description="X",
                                    estimated_materials_cents=100000, design_fee_cents=0),
        SA,
    )
    validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value, expected_status=404)


def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "Each list response reports its pagination state in the `meta` object via
    the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the
    number of records matching the query before pagination and `has_more` indicates whether
    records remain beyond the current page."

    Design: Corner/entities/list_customers_pagination_envelope
    """
    create_customer(full_name="P One", email="p1@x.com", phone="555-1004")
    create_customer(full_name="P Two", email="p2@x.com", phone="555-1005")
    data, meta = validate_paginated(api.list_customers(SA))
    assert meta["total_count"] >= 2
    assert "has_more" in meta


def test_payment_is_append_only_with_succeeded_outcome(api):
    """PRD §3.9: "A payment is created by a sales associate or manager, its `outcome` is set
    to `SUCCEEDED`, and it is append-only — it carries no `version` and is never modified."

    Design: Corner/entities/appraisal_immutable_after_void_no_version_on_payment
    """
    order, customer_id = create_quoted_custom_order(
        description="Ring", estimated_materials_cents=100000, design_fee_cents=0
    )
    res = api.create_payment(
        {"target_type": "CUSTOM_ORDER", "custom_order_id": order["id"], "amount_cents": 1000}, SA
    )
    payment = validate_success(res, 201)
    assert payment["outcome"] == "SUCCEEDED"
    assert "version" not in payment
