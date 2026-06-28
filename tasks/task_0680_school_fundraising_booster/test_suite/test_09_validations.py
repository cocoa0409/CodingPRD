"""Uniqueness, posture-gate, reference-existence, stock, and seller-block
validations (single-failure scenarios).

Covers corner queue B section: validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_campaign, add_prize_tier, add_seller, add_product,
    setup_active_catalog, setup_active_pledge, create_pledge,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]


def test_duplicate_product_sku_returns_duplicate_key(api, admin_headers):
    """PRD §3.4: "a `sku` that must be unique within the campaign ... A duplicate
    `sku` within the same campaign is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_product_sku_returns_duplicate_key
    """
    camp = create_campaign(campaign_type="CATALOG")
    add_product(camp["id"], sku="WRAP", name="Wrap")
    res = api.create_product({
        "campaign_id": camp["id"], "sku": "WRAP", "name": "Wrap2",
        "unit_price_cents": 2500, "unit_cost_cents": 900, "stock_qty": 50,
    }, admin_headers)
    validate_error(res, "ERR_DUPLICATE_KEY", expected_status=409)


def test_duplicate_prize_tier_threshold_returns_duplicate_key(api, admin_headers):
    """PRD §3.6: "The `threshold_cents` must be unique within a campaign; a
    duplicate threshold within the same campaign is rejected with
    `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_prize_tier_threshold_returns_duplicate_key
    """
    camp = create_campaign(campaign_type="CATALOG")
    add_prize_tier(camp["id"], label="A", threshold_cents=5000)
    res = api.create_prize_tier({
        "campaign_id": camp["id"], "label": "B", "threshold_cents": 5000,
        "prize_description": "q",
    }, admin_headers)
    validate_error(res, "ERR_DUPLICATE_KEY", expected_status=409)


def test_order_create_when_campaign_draft_returns_campaign_not_active(api, admin_headers):
    """PRD §3.1: "While a campaign is still in `DRAFT`, none of its children may
    be created or transitioned; this is the posture gate of Section 2.9
    surfacing as `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Corner/validations/order_create_when_campaign_draft_returns_campaign_not_active
    """
    camp = create_campaign(campaign_type="CATALOG")
    seller = add_seller(camp["id"])
    product = add_product(camp["id"], sku="WRAP", name="Wrap")
    res = api.create_order({
        "campaign_id": camp["id"], "seller_id": seller["id"],
        "buyer_name": "B", "buyer_email": "b@x.com",
        "lines": [{"product_id": product["id"], "quantity": 2}],
    }, admin_headers)
    validate_error(res, "ERR_CAMPAIGN_NOT_ACTIVE", expected_status=409)


def test_order_product_in_other_campaign_returns_reference_not_found(api, admin_headers):
    """PRD §2.6: "when a `campaign_id`, `seller_id`, `product_id`, or
    `volunteer_id` supplied in the body either does not exist or does not
    belong to the named campaign, the request is rejected with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/order_create_product_in_other_campaign_returns_reference_not_found
    """
    camp_a, seller_a, _ = setup_active_catalog()
    camp_b = create_campaign(campaign_type="CATALOG", name="B")
    prod_b = add_product(camp_b["id"], sku="WRAP", name="Wrap")  # belongs to B
    res = api.create_order({
        "campaign_id": camp_a["id"], "seller_id": seller_a["id"],
        "buyer_name": "B", "buyer_email": "b@x.com",
        "lines": [{"product_id": prod_b["id"], "quantity": 2}],
    }, admin_headers)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=404)


def test_insufficient_stock_one_over_headroom_returns_error(api, admin_headers):
    """PRD §3.4: "the requested quantity for a product must be no greater than
    that product's `stock_qty` minus its current `reserved_qty` ... A line
    that would over-reserve is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/insufficient_stock_one_over_headroom_returns_error
    """
    camp, seller, product = setup_active_catalog(stock_qty=10)
    res = api.create_order({
        "campaign_id": camp["id"], "seller_id": seller["id"],
        "buyer_name": "B", "buyer_email": "b@x.com",
        "lines": [{"product_id": product["id"], "quantity": 11}],
    }, admin_headers)
    validate_error(res, "ERR_INSUFFICIENT_STOCK", expected_status=409)


def test_pledge_record_when_seller_blocked_returns_seller_blocked(api, admin_headers):
    """PRD §3.3: "while a seller is `BLOCKED`, three revenue-affecting
    transitions naming that seller are refused with `ERR_SELLER_BLOCKED`:
    paying one of their orders, recording one of their pledges, and collecting
    one of their pledges."

    Design: Corner/validations/pledge_record_when_seller_blocked_returns_seller_blocked
    """
    # PRD §3.3: blocking a seller cancels their still-PROMISED pledges, so a
    # pledge created before the block would be CANCELLED and record would trip
    # state-legality (ERR_INVALID_STATE) before the seller-block guard. Pledge
    # create carries no seller-block guard (PRD §2.9 scopes that guard to
    # pay/record/collect), so block first, then create the pledge: it stays
    # PROMISED with a BLOCKED crediting seller, and recording it reaches the
    # seller-block guard -> ERR_SELLER_BLOCKED.
    camp, seller = setup_active_pledge()
    api_client.block_seller(seller["id"], ADMIN)
    pledge = create_pledge(camp["id"], seller["id"], per_unit_cents=100, flat_cents=0)
    res = api.record_pledge(pledge["id"], {"units_recorded": 10}, admin_headers)
    validate_error(res, "ERR_SELLER_BLOCKED", expected_status=409)
