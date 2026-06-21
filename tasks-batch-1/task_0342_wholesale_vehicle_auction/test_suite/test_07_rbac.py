"""Role-based access control: missing auth, forbidden roles, and peer-role ownership."""
import pytest

from test_helpers import (
    make_admin_headers, make_seller_headers, make_buyer_headers,
    get_success_data, validate_error,
    setup_paid_settlement_with_open_claim, setup_running_sale_with_lot,
    open_bidding,
)
import test_helpers as th


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api._request("GET", "/auction/sales", headers={})
    validate_error(resp, "ERR_MISSING_AUTH_CONTEXT")


def test_seller_cannot_create_sale_forbidden(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/seller_cannot_create_sale_forbidden
    """
    seller_headers = make_seller_headers("00000000-0000-4000-8000-000000000001")
    resp = api.create_sale(th.factories.create_sale_payload(), seller_headers)
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


def test_buyer_cannot_rule_arbitration_forbidden(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_rule_arbitration_forbidden
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE")
    # Buyer (B1) tries to rule on the claim — an Arbitrator-exclusive op.
    resp = api.rule_arbitration_claim(ctx["claim"]["id"], make_buyer_headers(ctx["b1"]["id"]))
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


def test_buyer_cannot_bid_as_another_buyer_not_owner(api):
    """PRD §2.1: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting
    `Buyer`; ownership-scoped operations compare the resource's buyer foreign key to
    `X-User-ID` (a bid ... carries a `buyer_id` that must equal `X-User-ID`). When an
    entity-backed `Seller` or `Buyer` attempts to act on a resource it does not own, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/buyer_cannot_bid_as_another_buyer_not_owner
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, starting_bid_cents=400000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    # Body buyer_id = B2 but X-User-ID = B1 -> acting as another buyer.
    resp = api.place_bid(
        ctx["lot"]["id"],
        th.factories.place_bid_payload(b2["id"], lot_open["version"], bid_type="LIVE",
                                       amount_cents=400000, channel="LANE"),
        make_buyer_headers(b1["id"]),
    )
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")
