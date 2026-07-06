"""Onboarding, intake defaults, not-found, RBAC, and list pagination.

Covers seller creation defaults, item intake validation, resource not-found,
role authorization, and paginated list metadata (PRD §2.1, §2.3, §2.9, §3.1, §3.2).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_seller_payload, create_item_payload, create_category_policy_payload,
    TEST_USERS, NON_EXISTENT_UUID, make_seller_headers, make_buyer_headers,
)
from test_helpers import create_seller, create_buyer  # fixtures


def test_seller_creation_sets_active_standard_zero_ledgers(api):
    """PRD §3.1: "A newly created seller starts with `status` `ACTIVE`, `tier`
    `STANDARD`, and every ledger field — `lifetime_net_sales_cents`,
    `pending_payout_cents`, `released_payout_cents`, `reversed_payout_cents`, and
    `payout_balance_cents` — initialised to zero."

    Design: Corner/entities/seller_creation_sets_defaults
    """
    res = api.create_seller(create_seller_payload(display_name="S1", email="s1@x.com"),
                            TEST_USERS["ops_admin_headers"])
    seller = validate_success(res, 201)
    assert seller["status"] == "ACTIVE", seller["status"]
    assert seller["tier"] == "STANDARD", seller["tier"]
    assert seller["lifetime_net_sales_cents"] == 0
    assert seller["pending_payout_cents"] == 0
    assert seller["released_payout_cents"] == 0
    assert seller["reversed_payout_cents"] == 0
    assert seller["payout_balance_cents"] == 0


def test_item_create_missing_category_returns_validation(api):
    """PRD §2.1: "A syntactically malformed body — a missing required field, an
    unrecognised enumeration value, or a non-integer value where whole cents are
    required — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/item_create_missing_required_category_returns_validation
    """
    seller = create_seller()
    payload = create_item_payload(seller["id"])
    del payload["category"]
    res = api.create_item(payload, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_get_nonexistent_listing_returns_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve to an existing resource
    produces the corresponding not-found error before any later identifier is examined.
    The not-found codes are resource-specific: `ERR_SELLER_NOT_FOUND`,
    `ERR_BUYER_NOT_FOUND`, `ERR_CATEGORY_POLICY_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`,"

    Design: Corner/entities/get_nonexistent_listing_returns_not_found
    """
    res = api.get_listing(NON_EXISTENT_UUID, TEST_USERS["ops_admin_headers"])
    validate_error(res, "ERR_LISTING_NOT_FOUND", expected_status=404)


def test_item_dropoff_created_in_received_state(api):
    """PRD §3.2: "A `DROP_OFF` item is received on the spot: it is created directly in
    `RECEIVED` status, moving from the notional `INTAKE_REQUESTED` state to `RECEIVED`
    automatically at creation."

    Design: Corner/entities/item_dropoff_created_in_received_state
    """
    seller = create_seller()
    res = api.create_item(
        create_item_payload(seller["id"], category="HANDBAGS", intake_channel="DROP_OFF"),
        make_seller_headers(seller["id"]))
    item = validate_success(res, 201)
    assert item["status"] == "RECEIVED", item["status"]


def test_buyer_cannot_create_category_policy(api):
    """PRD §2.1: "When a role is syntactically valid but not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "An `OpsAdmin` creates a `CategoryPolicy` for a `category`, which must be
    one of `HANDBAGS`, `WATCHES`, `JEWELRY`, `APPAREL`, or `SHOES`, and each category may
    have at most one policy."

    Design: Corner/rbac/rbac_buyer_cannot_create_category_policy
    """
    buyer = create_buyer()
    res = api.create_category_policy(
        create_category_policy_payload(category="WATCHES", base_commission_pct=0.15),
        make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_items_list_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "The `meta` object of every list response reports `limit`, `offset`,
    `total_count` (the total number of matching resources ignoring pagination), and
    `has_more` (whether any matching resources remain beyond the current page)."

    Design: Corner/endpoints/items_list_pagination_total_and_has_more
    """
    seller = create_seller()
    headers = make_seller_headers(seller["id"])
    for title in ("One", "Two"):
        api.create_item(create_item_payload(seller["id"], category="HANDBAGS",
                                            intake_channel="DROP_OFF", title=title), headers)
    res = api.list_items(TEST_USERS["ops_admin_headers"],
                         params={"seller_id": seller["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
    assert len(data) == 1, len(data)
