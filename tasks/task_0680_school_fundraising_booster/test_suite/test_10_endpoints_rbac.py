"""Endpoint reads (disbursement read-back, filtered listing) and RBAC
segregation (read-only role, segregation of duties, seller ownership, auth).

Covers corner queue B sections: endpoints, rbac.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_active_catalog,
    place_and_pay_order, create_collected_pledge,
    add_seller,
    close_campaign, reconcile_campaign, disburse_campaign,
    make_seller_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── endpoints ─────────────────────────────────────────────────────────────

def test_disburse_creates_readable_disbursement(api, school_official_headers):
    """PRD §3.7: "Disbursement creates a **Disbursement** record naming the
    `campaign_id`, copying the snapshot's `school_profit_cents` into
    `school_amount_cents` and `vendor_payable_cents` into
    `vendor_amount_cents`"

    Design: Corner/endpoints/disburse_creates_readable_disbursement
    """
    camp, seller, product = setup_active_catalog(profit_split_pct=0.60)
    place_and_pay_order(camp["id"], seller["id"], product["id"], 5)  # gross 10000
    create_collected_pledge(camp["id"], seller["id"], per_unit_cents=0,
                            units_recorded=0, flat_cents=5000)
    closed = close_campaign(camp["id"])
    reconciled = reconcile_campaign(camp["id"], closed["version"])
    disburse_campaign(camp["id"], reconciled["version"], memo="EOY payout")

    data, meta = validate_paginated(
        api.list_disbursements(school_official_headers, params={"campaign_id": camp["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["school_amount_cents"] == 6600
    assert data[0]["vendor_amount_cents"] == 8400


def test_orders_filtered_list_by_seller_id(api, school_official_headers):
    """PRD §4 (GET /fundraising/orders): "List orders (filter by campaign_id /
    seller_id / payment_status / fulfillment_status)"

    Design: Corner/endpoints/orders_filtered_list_by_seller_id
    """
    camp, seller1, product = setup_active_catalog()
    seller2 = add_seller(camp["id"], display_name="S2", guardian_email="g2@x.com")
    api_client.create_order({
        "campaign_id": camp["id"], "seller_id": seller1["id"],
        "buyer_name": "B", "buyer_email": "b@x.com",
        "lines": [{"product_id": product["id"], "quantity": 2}],
    }, ADMIN)
    data, meta = validate_paginated(
        api.list_orders(school_official_headers, params={"seller_id": seller2["id"]}))
    assert meta["total_count"] == 0
    assert len(data) == 0


# ─── rbac ──────────────────────────────────────────────────────────────────

def test_school_official_cannot_create_campaign(api, school_official_headers):
    """PRD §2.1: "When the headers are present but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/school_official_cannot_create_campaign
    """
    res = api.create_campaign({
        "name": "C", "campaign_type": "CATALOG", "goal_cents": 100000,
        "profit_split_pct": 0.50, "vendor_name": "V",
        "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-05-01T00:00:00Z",
    }, school_official_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_campaign_admin_cannot_reconcile(api, admin_headers):
    """PRD §2.1: "The `CampaignAdmin` is deliberately segregated from
    the money-settlement duties."

    Design: Corner/rbac/campaign_admin_cannot_reconcile
    """
    closed = close_campaign(setup_active_catalog()[0]["id"])
    res = api.reconcile_campaign(
        closed["id"], {"expected_campaign_version": closed["version"]}, admin_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_seller_cannot_place_order_for_other_seller(api):
    """PRD §2.1: "A `Seller` may place an order or create a pledge only when
    crediting themselves — that is, the `seller_id` in the request body must
    equal `X-User-ID` ... An attempt by a `Seller` to act on another seller's
    order or pledge is an `ERR_FORBIDDEN` rejection."

    Design: Corner/rbac/seller_cannot_place_order_for_other_seller
    """
    camp, seller1, product = setup_active_catalog()
    seller2 = add_seller(camp["id"], display_name="S2", guardian_email="g2@x.com")
    res = api.create_order({
        "campaign_id": camp["id"], "seller_id": seller2["id"],
        "buyer_name": "B", "buyer_email": "b@x.com",
        "lines": [{"product_id": product["id"], "quantity": 2}],
    }, make_seller_headers(seller1["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one,
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_campaigns(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
