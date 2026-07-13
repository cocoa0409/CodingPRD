"""Account onboarding defaults, product catalog defaults, not-found and validation
basics, and list pagination.

Every test builds its own state from scratch (the server database is empty at the
start of each test).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_buyer_headers,
    account_payload, product_payload,
    assert_account, assert_product,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]
BUYER = TEST_USERS["buyer_headers"]


def test_create_account_applies_defaults_and_system_fields(api):
    """PRD §3.1: "An optional `tax_rate` may be supplied; when omitted it defaults to 0.08".
    PRD §3.1: "A newly created account begins with `status` set to `ACTIVE`, `tax_exempt_status`
    set to `NONE`, an outstanding balance of zero, and `version` 1."

    Design: Corner/entities/create_account_defaults_and_system_fields
    """
    created = validate_success(
        api.create_account(account_payload(business_name="Defaults Co", credit_terms="NET_30",
                                           credit_limit_cents=50000), AM),
        201,
    )
    fetched = validate_success(api.get_account(created["id"], WH))
    assert_account(fetched)
    assert fetched["tax_rate"] == 0.08, f"tax_rate default must be 0.08, got {fetched['tax_rate']}"
    assert fetched["status"] == "ACTIVE"
    assert fetched["tax_exempt_status"] == "NONE"
    assert fetched["outstanding_cents"] == 0
    assert fetched["version"] == 1


def test_create_product_taxable_defaults_true_and_no_reorder(api):
    """PRD §3.3: "A `taxable` flag (defaulting to true) controls whether the product's line
    subtotal is taxed."
    PRD §3.3: "The `needs_reorder` flag is true exactly when `on_hand_qty` is less than or equal
    to `reorder_point`."

    Design: Corner/entities/create_product_taxable_defaults_true
    """
    payload = product_payload(sku="DFLT-1", name="Ladle", category="SMALLWARE",
                              unit_price_cents=400, case_qty=12, case_price_cents=4200,
                              pallet_case_qty=10, pallet_price_cents=40000, weight_lbs_per_unit=1,
                              fulfillment_type="STOCK", freight_type="PARCEL",
                              on_hand_qty=20, par_level=30, reorder_point=5)
    payload.pop("taxable")  # exercise the default
    created = validate_success(api.create_product(payload, WH), 201)
    fetched = validate_success(api.get_product(created["id"], BUYER))
    assert_product(fetched)
    assert fetched["taxable"] is True
    assert fetched["needs_reorder"] is False
    assert fetched["reorder_suggested_qty"] == 0


def test_get_unknown_order_returns_not_found(api):
    """PRD §2.7: "the first identifier that does not resolve produces the corresponding not-found
    error (for instance `ERR_ACCOUNT_NOT_FOUND`, `ERR_CERT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`"

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order("00000000-0000-4000-8000-000000000000", WH)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_create_product_missing_sku_is_invalid_request(api):
    """PRD §3.9: "a malformed body, an unknown enum value, or an out-of-range numeric field (for
    example a negative quantity, a `case_qty` below 1, or an unrecognized category) is rejected
    with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_product_missing_sku_invalid_request
    """
    payload = product_payload(name="No SKU", category="SMALLWARE", unit_price_cents=400,
                              case_qty=12, case_price_cents=4200, pallet_case_qty=10,
                              pallet_price_cents=40000, weight_lbs_per_unit=1,
                              fulfillment_type="STOCK", freight_type="PARCEL",
                              on_hand_qty=20, par_level=30, reorder_point=5)
    payload.pop("sku")
    resp = api.create_product(payload, WH)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_products_reports_total_and_has_more(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the count of all matching items
    before pagination and `has_more` indicates whether items remain beyond the current page."

    Design: Corner/entities/list_products_pagination_envelope
    """
    validate_success(api.create_product(product_payload(sku="PG-1", on_hand_qty=10, par_level=20,
                                                        reorder_point=2), WH), 201)
    validate_success(api.create_product(product_payload(sku="PG-2", on_hand_qty=10, par_level=20,
                                                        reorder_point=2), WH), 201)
    data, meta = validate_paginated(api.list_products(BUYER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1
