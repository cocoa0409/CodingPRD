"""Order creation envelope and product listing pagination."""
from test_helpers import (
    validate_success, validate_paginated,
    create_customer, make_customer_headers, create_order_payload,
    TEST_USERS,
)


def test_create_order_returns_building_unpaid_version_one(api):
    """PRD §3.4: "An order is created for a customer, optionally seeded from a
    project bundle via project_bundle_id, and begins with fulfillment_status of
    BUILDING and payment_status of UNPAID."
    PRD §2.4: "The version begins at 1 when the resource is created and
    increments by one on every mutation of that resource"

    Design: Corner/endpoints/create_order_success_envelope_shape
    """
    customer = create_customer()
    resp = api.create_order(
        create_order_payload(customer["id"]), make_customer_headers(customer["id"])
    )
    data = validate_success(resp, expected_status=201)
    assert data["fulfillment_status"] == "BUILDING"
    assert data["payment_status"] == "UNPAID"
    assert data["version"] == 1


def test_list_products_pagination_defaults(api):
    """PRD §2.3: "The limit parameter defaults to 10, has a minimum of 1, and has
    a maximum of 100. The offset parameter defaults to 0 and has a minimum of 0."

    Design: Corner/endpoints/list_products_pagination_defaults
    """
    resp = api.list_products(TEST_USERS["store_manager_headers"])
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
