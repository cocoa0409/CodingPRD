"""Role-based access control, resource ownership, invalid user context headers, and
foreign-key reverse listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_buyer_headers, build_user_headers,
    product_payload,
    fixtures,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# rbac / buyer_cannot_create_product_forbidden (corner)
# --------------------------------------------------------------------------- #
def test_buyer_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/buyer_cannot_create_product_forbidden
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    resp = api.create_product(product_payload(sku="X-1", name="X", on_hand_qty=10, par_level=20,
                                              reorder_point=2),
                              make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# --------------------------------------------------------------------------- #
# rbac / buyer_cannot_confirm_other_accounts_order_forbidden (corner)
# --------------------------------------------------------------------------- #
def test_buyer_cannot_confirm_another_accounts_order(api):
    """PRD §2.1: "for orders, returns, and certificates, the resource's `account_id` (directly, or
    transitively through the order for returns and lines) must equal the `Buyer`'s `X-User-ID`; a
    mismatch is rejected with `ERR_NOT_ACCOUNT_OWNER`."

    Design: Corner/rbac/buyer_cannot_confirm_other_accounts_order_forbidden
    """
    acct1 = fixtures.create_account(api, business_name="Owner1")
    acct2 = fixtures.create_account(api, business_name="Owner2")
    prod = fixtures.create_product(api, sku="OWN-1", name="Grater", unit_price_cents=300,
                                   case_qty=12, case_price_cents=3200, pallet_case_qty=10,
                                   pallet_price_cents=30000, par_level=50)
    order = fixtures.create_order(api, acct1["id"])
    fixtures.add_line(api, order["id"], acct1["id"], prod["id"], 3)
    version = fixtures.account_version(api, acct1["id"])
    resp = api.confirm_order(order["id"], {"expected_account_version": version},
                             make_buyer_headers(acct2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value)


# --------------------------------------------------------------------------- #
# rbac / create_account_invalid_user_header_returns_400 (corner)
# --------------------------------------------------------------------------- #
def test_unrecognized_role_rejected_with_header_error(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized value, is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/create_account_invalid_user_header_returns_400
    """
    ghost_headers = build_user_headers("ghost-1", "Ghost")
    resp = api.create_account(
        {"business_name": "Ghost Co", "credit_terms": "NET_30", "credit_limit_cents": 100000},
        ghost_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# --------------------------------------------------------------------------- #
# endpoints / fk_reverse_list_lines_by_product (corner)
# --------------------------------------------------------------------------- #
def test_list_order_lines_filtered_by_product(api):
    """PRD §2.7: "order lines may be filtered by `order_id` and/or `product_id`".

    Design: Corner/endpoints/fk_reverse_list_lines_by_product
    """
    acct = fixtures.create_account(api, credit_limit_cents=100000)
    prod = fixtures.create_product(api, sku="FK-1", name="Skimmer", unit_price_cents=300,
                                   case_qty=12, case_price_cents=3200, pallet_case_qty=10,
                                   pallet_price_cents=30000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    line = fixtures.add_line(api, order["id"], acct["id"], prod["id"], 3)
    data, meta = validate_paginated(api.list_order_lines_filtered(WH, params={"product_id": prod["id"]}))
    assert meta["total_count"] == 1
    assert any(item["id"] == line["id"] for item in data), "created line must appear in results"
