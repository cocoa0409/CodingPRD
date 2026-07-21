"""Onboarding, required-field validation, not-found reads, list reverse-reachability, and RBAC denials."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_broker_headers, make_seller_headers,
    create_buyer_payload, create_listing_payload,
    assert_buyer,
)
from test_helpers import fixtures as fx


def test_buyer_onboarding_sets_available_capital_to_proof_of_funds(api):
    """PRD §3.1: "the buyer's `committed_capital_cents` and `escrowed_cents` both start at
    zero, and the derived `available_capital_cents` therefore starts equal to `proof_of_funds_cents`."

    Design: Corner/entities/buyer_creation_sets_available_capital
    """
    resp = api.create_buyer(
        create_buyer_payload(proof_of_funds_cents=50_000_000, net_worth_cents=150_000_000),
        TEST_USERS["platform_admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert_buyer(data)
    assert data["available_capital_cents"] == 50_000_000
    assert data["committed_capital_cents"] == 0
    assert data["escrowed_cents"] == 0


def test_listing_create_missing_asking_price_rejected(api):
    """PRD §2.6: "A malformed body, a missing required field, or a bad enum value is rejected
    with `ERR_VALIDATION` (400)."

    Design: Corner/entities/listing_create_missing_required_field_returns_validation
    """
    broker = fx.onboard_broker(api)
    seller = fx.onboard_seller(api)
    payload = create_listing_payload(seller["id"], business_name="No Price Co")
    payload.pop("asking_price_cents")
    resp = api.create_listing(payload, make_broker_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_unknown_buyer_returns_not_found(api):
    """PRD §2.5: "the server validates existence left to right and rejects the request at the
    first identifier that does not resolve, returning the not-found error specific to that
    resource type."

    Design: Corner/entities/get_buyer_not_found_returns_404
    """
    resp = api.get_buyer(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(resp, ApiErrorId.ERR_BUYER_NOT_FOUND.value)


def test_list_listings_returns_array_with_seller_fk(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, all list responses are sorted by
    their creation timestamp (`created_at`) in ascending order."
    PRD §3.2: "The creation payload carries the `seller_id` of the owner, the `business_name`,
    an `industry_code`"

    Design: Corner/endpoints/listings_filtered_by_seller_reverse_reach
    """
    broker = fx.onboard_broker(api)
    seller = fx.onboard_seller(api)
    listing = fx.create_listing(api, broker["id"], seller["id"])
    resp = api.list_listings(make_broker_headers(broker["id"]), params={"seller_id": seller["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1
    assert any(row["id"] == listing["id"] and row["seller_id"] == seller["id"] for row in data)


def test_list_lois_on_deal_returns_array_with_deal_fk(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, all list responses are sorted by
    their creation timestamp (`created_at`) in ascending order."
    PRD §3.5: "Every LOI belongs to its deal, recorded through the offer's `deal_id`."

    Design: Corner/endpoints/lois_subresource_reverse_reach
    """
    s = fx.setup_submitted_loi(api)
    resp = api.list_lois(s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1
    assert any(row["id"] == s["loi"]["id"] and row["deal_id"] == s["deal"]["id"] for row in data)


def test_buyer_cannot_create_listing(api):
    """PRD §2.1: "When the headers are valid but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/buyer_cannot_create_listing_returns_unauthorized
    """
    seller = fx.onboard_seller(api)
    buyer = fx.onboard_buyer(api)
    from test_helpers import make_buyer_headers
    resp = api.create_listing(create_listing_payload(seller["id"]), make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_non_owning_seller_cannot_accept_loi(api):
    """PRD §2.1: "the seller owns the listing side of a deal, and ownership checks on offer-side
    actions compare the `seller_id` of the listing behind the offer to `X-User-ID`."
    PRD §2.1: "When an entity-backed actor targets a resource they do not own, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/non_owner_seller_cannot_accept_loi_returns_not_owner
    """
    s = fx.setup_submitted_loi(api)
    other_seller = fx.onboard_seller(api, full_name="Seller Two", email="s2@x.com")
    resp = api.accept_loi(s["loi"]["id"], make_seller_headers(other_seller["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
