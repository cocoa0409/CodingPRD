"""Role-based access control and self-dealing corners."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS,
    create_release_payload,
    create_account, create_sku, create_listing, make_seller_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def test_seller_cannot_create_release_unauthorized(api):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    (PRD §4 authorizes only PlatformAdmin for POST /releases.)

    Design: Corner/rbac/create_release_wrong_role_returns_unauthorized
    """
    sku = create_sku(api)
    seller = create_account(api, full_name="RBAC Seller")
    payload = create_release_payload(sku_id=sku["id"], allocated_quantity=2)
    resp = api.create_release(payload, make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_clock_set_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/clock_set_missing_auth_returns_unauthenticated
    """
    resp = api.set_clock("2026-07-02T00:00:00Z", {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_buying_own_listing_rejected_as_self_purchase(api):
    """PRD §3.5: "the buyer must not be the listing's own seller — a
    `buyer_account_id` equal to the listing's `seller_account_id` is rejected
    with `ERR_SELF_PURCHASE`"

    Design: Corner/rbac/self_purchase_own_listing_rejected
    """
    sku = create_sku(api)
    acct = create_account(api, full_name="Self Dealer")
    listing = create_listing(api, sku["id"], acct["id"], ask_price_cents=30000)
    resp = api.buy_listing(listing["id"], make_buyer_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_PURCHASE.value)
