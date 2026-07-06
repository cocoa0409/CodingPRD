"""Role authorization and resource ownership: authentication, role, and owner checks."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_seller_headers, make_buyer_headers, anonymous_headers,
    create_shop, create_shipping_profile, create_listing,
    setup_active_listing, place_order,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Corner / rbac / buyer_cannot_publish_listing_returns_unauthorized
# ==========================================================================
def test_buyer_cannot_publish_listing(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_publish_listing_returns_unauthorized
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    listing = create_listing(shop["id"], sp["id"], title="Mug", price_cents=2000, quantity=5)
    resp = api.publish_listing(listing["id"], BUYER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ==========================================================================
# Corner / rbac / seller_cannot_create_shop_returns_unauthorized
# ==========================================================================
def test_seller_cannot_create_shop(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/seller_cannot_create_shop_returns_unauthorized
    """
    shop = create_shop()
    resp = api.create_shop(
        {"owner_seller_id": "seller_2", "name": "Sneaky Shop"},
        make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ==========================================================================
# Corner / rbac / seller_not_owner_create_listing_returns_not_shop_owner
# ==========================================================================
def test_seller_creating_listing_under_other_shop_returns_not_owner(api):
    """PRD §2.1: "Ownership checks on any shop-scoped resource compare that resource's
    `shop_id` to `X-User-ID` ... A shop-scoped mutation whose target does not belong to
    the acting seller is rejected with `ERR_NOT_SHOP_OWNER` (HTTP 403)."

    Design: Corner/rbac/seller_not_owner_create_listing_returns_not_shop_owner
    """
    shop_a = create_shop(owner_seller_id="seller_a", name="Shop A")
    shop_b = create_shop(owner_seller_id="seller_b", name="Shop B")
    sp_b = create_shipping_profile(shop_b["id"])
    resp = api.create_listing(
        {"shop_id": shop_b["id"], "shipping_profile_id": sp_b["id"], "title": "Cross Shop",
         "fulfillment_type": "READY_TO_SHIP", "processing_time_days": 1,
         "price_cents": 2000, "quantity": 1},
        make_seller_headers(shop_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_SHOP_OWNER)


# ==========================================================================
# Corner / rbac / unauthenticated_missing_role_returns_401
# ==========================================================================
def test_request_without_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_role_returns_401
    """
    resp = api.create_shop(
        {"owner_seller_id": "seller_1", "name": "Handmade Co"}, anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ==========================================================================
# Corner / rbac / buyer_cannot_pay_others_order_returns_not_shop_owner
# ==========================================================================
def test_buyer_cannot_pay_another_buyers_order(api):
    """PRD §2.1: "Ownership of a buyer action is enforced by comparing `X-User-ID` to the
    target order's stored `buyer_id`; a mismatch is rejected with `ERR_NOT_SHOP_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_pay_others_order_returns_not_shop_owner
    """
    shop, sp, listing = setup_active_listing(
        listing_overrides={"price_cents": 2000, "quantity": 5, "title": "Mug"})
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    resp = api.pay_order(order["id"], make_buyer_headers("buyer_2"))
    validate_error(resp, ApiErrorId.ERR_NOT_SHOP_OWNER)
