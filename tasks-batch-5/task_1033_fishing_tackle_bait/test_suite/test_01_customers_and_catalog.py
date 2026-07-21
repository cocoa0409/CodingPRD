"""Customer registration, catalog basics, listing, and a catalog RBAC denial."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_customer_headers,
    assert_customer,
    customer_payload, product_payload,
    fixtures,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_customer_registration_initializes_loyalty_defaults(api):
    """PRD 3.1: "At registration the loyalty state is initialized: the `loyalty_ledger` starts empty, `loyalty_points_balance` is zero, `loyalty_tier` is `BRONZE`, and `lifetime_spend_cents` is zero."

    Design: Corner/entities/entity_customer_create_returns_201_with_loyalty_defaults
    """
    resp = api.create_customer(
        customer_payload(name="New C", email="n@x.com", state_code="CA", birth_date="1990-05-05"),
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert_customer(data)
    assert data["loyalty_points_balance"] == 0
    assert data["loyalty_tier"] == "BRONZE"
    assert data["lifetime_spend_cents"] == 0
    assert data["loyalty_ledger"] == []

    # Re-read confirms the persisted defaults.
    got = validate_success(api.get_customer(data["id"], CLERK))
    assert got["loyalty_points_balance"] == 0
    assert got["loyalty_tier"] == "BRONZE"
    assert got["lifetime_spend_cents"] == 0


def test_get_missing_customer_returns_not_found(api):
    """PRD 2.4: "the path resource and every referenced foreign-key `id` must exist; existence is validated left to right, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/entity_customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_price_rejected(api):
    """PRD 2.8: "Request well-formedness** — required fields present, enums and types valid, and quantities, weights, and counts positive where required, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/entity_product_missing_required_field_returns_invalid_request
    """
    payload = {"sku": "NOPRICE", "name": "No Price", "category": "ROD", "stock_qty": 5}
    resp = api.create_product(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_client_supplied_loyalty_balance_ignored_at_registration(api):
    """PRD 3.1: "At registration the loyalty state is initialized: the `loyalty_ledger` starts empty, `loyalty_points_balance` is zero, `loyalty_tier` is `BRONZE`, and `lifetime_spend_cents` is zero."

    Design: Corner/entities/entity_customer_system_field_input_ignored
    """
    payload = customer_payload(
        name="Sneaky", email="s@x.com", state_code="CA",
        birth_date="1990-05-05", loyalty_points_balance=999,
    )
    resp = api.create_customer(payload, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["loyalty_points_balance"] == 0, "supplied 999 must be ignored"


def test_products_list_pagination_reports_meta(api):
    """PRD 2.3: "Every list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page) inside `meta`."

    Design: Corner/endpoints/endpoint_products_list_pagination
    """
    fixtures.create_product(sku="PG-1", name="P1", category="ROD", unit_price_cents=1000, stock_qty=5)
    fixtures.create_product(sku="PG-2", name="P2", category="REEL", unit_price_cents=2000, stock_qty=5)
    fixtures.create_product(sku="PG-3", name="P3", category="APPAREL", unit_price_cents=3000, stock_qty=5)

    resp = api.list_products(CLERK, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 items on the page, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_customer_cannot_create_product(api):
    """PRD 2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_customer_cannot_create_product
    """
    customer = fixtures.create_customer(name="Role Cust", email="rc@x.com")
    payload = product_payload(sku="RB-1", name="Sneaky Rod", category="ROD",
                              unit_price_cents=1000, stock_qty=5)
    resp = api.create_product(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
