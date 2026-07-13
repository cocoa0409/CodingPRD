"""Catalog creation, customer registration, listing, and access-control corners."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NO_AUTH_HEADERS,
    make_customer_headers,
    create_franchisee_payload, create_menu_item_payload, create_customer_payload,
    create_customer,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
NON_EXISTENT_STORE = "00000000-0000-0000-0000-000000000000"


def test_franchisee_creation_sets_system_fields(api):
    """PRD §2.4: "the `version` field is an integer that starts at 1 and increments
    by one on every mutation of the resource."
    PRD §3.1: "A franchisee also carries a running `lifetime_royalty_cents`, which
    starts at 0 and accumulates the total franchise amount due across all posted
    reconciliations of that franchisee's stores."

    Design: Corner/entities/franchisee_creation_sets_system_fields
    """
    resp = api.create_franchisee(create_franchisee_payload(legal_name="Acme Juice"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"
    assert data["lifetime_royalty_cents"] == 0, (
        f"Expected lifetime_royalty_cents 0, got {data['lifetime_royalty_cents']}"
    )


def test_customer_defaults_bronze_zero_balance(api):
    """PRD §3.3: "A new customer starts at loyalty tier `BRONZE`, with `points_balance`
    and `lifetime_points_earned` both 0."

    Design: Corner/entities/customer_defaults_bronze_zero_balance
    """
    resp = api.create_customer(create_customer_payload(email="d@x.com", full_name="Dee"), ANON)
    data = validate_success(resp, expected_status=201)
    assert data["loyalty_tier"] == "BRONZE"
    assert data["points_balance"] == 0
    assert data["lifetime_points_earned"] == 0


def test_get_store_not_found(api):
    """PRD §2.8: "the first identifier in the path that does not correspond to an
    existing resource causes the request to fail with `ERR_NOT_FOUND`, before any
    deeper resource is consulted."

    Design: Corner/entities/get_store_not_found
    """
    resp = api.get_store(NON_EXISTENT_STORE, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_menu_item_missing_required_returns_invalid_request(api):
    """PRD §2.9: "Request well-formedness — required fields present, enum members
    valid, numeric fields not negative, pagination in range, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_menu_item_missing_required_returns_invalid_request
    """
    payload = {"name": "NoPrice", "category": "SMOOTHIE", "recipe": [], "base_calories": 100}
    resp = api.create_menu_item(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_menu_items_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_menu_items_pagination
    """
    api.create_menu_item(create_menu_item_payload(name="A", category="JUICE",
                                                   base_price_cents=300, base_calories=100), ADMIN)
    api.create_menu_item(create_menu_item_payload(name="B", category="JUICE",
                                                   base_price_cents=400, base_calories=120), ADMIN)
    resp = api.list_menu_items(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"Expected 1 item with limit=1, got {len(data)}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "Expected has_more true with 2 items and limit 1"


def test_customer_cannot_create_menu_item_returns_unauthorized(api):
    """PRD §2.1: "the system checks whether the declared role is permitted to perform
    the requested operation; if not, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_menu_item_returns_unauthorized
    """
    cust = create_customer(api, email="r@x.com", full_name="Arr")
    payload = create_menu_item_payload(name="Hack", category="JUICE",
                                       base_price_cents=100, base_calories=10)
    resp = api.create_menu_item(payload, make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_read_other_customer_returns_not_resource_owner(api):
    """PRD §2.1: "When an authenticated, role-authorized caller targets a resource
    they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_read_other_customer_returns_not_resource_owner
    """
    cust_a = create_customer(api, email="aa@x.com", full_name="A A")
    cust_b = create_customer(api, email="bb@x.com", full_name="B B")
    resp = api.get_customer(cust_b["id"], make_customer_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_get_customer_missing_auth_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/get_customer_missing_auth_returns_unauthenticated
    """
    cust = create_customer(api, email="au@x.com", full_name="Auth")
    resp = api.get_customer(cust["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
