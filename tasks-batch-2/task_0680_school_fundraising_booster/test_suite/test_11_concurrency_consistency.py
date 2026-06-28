"""Optimistic concurrency (version increment on reconcile, stale-version
rejection on disburse), cascade reservation release on seller block, just-below
prize threshold, and immediate consistency.

Covers corner queue B sections: cross_cutting_complexity_layers, consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_active_catalog, setup_active_pledge,
    place_simple_order, place_and_pay_order, add_prize_tier,
    close_campaign, reconcile_campaign,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── cross_cutting_complexity_layers ──────────────────────────────────────

def test_occ_reconcile_version_increments_on_success(api):
    """PRD §3.7: "Reconciliation snapshots the final profit split onto the
    campaign, sets `reconciled_at` to the current logical-clock instant, and
    increments the campaign's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_reconcile_version_increments_on_success
    """
    camp, _ = setup_active_pledge()
    closed = close_campaign(camp["id"])
    reconciled = validate_success(api.reconcile_campaign(
        camp["id"], {"expected_campaign_version": closed["version"]}, TREASURER), 200)
    assert reconciled["posture"] == "RECONCILED"
    assert reconciled["version"] == closed["version"] + 1, \
        "reconcile must increment the campaign version by 1"


def test_occ_disburse_stale_version_rejected(api):
    """PRD §2.7: "Because the reconcile step itself increments the campaign
    `version`, a disburse request whose `expected_campaign_version` predates
    the reconcile would be paying out a view the client never confirmed; it is
    rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_disburse_stale_version_rejected
    """
    camp, _ = setup_active_pledge()
    closed = close_campaign(camp["id"])
    reconciled = reconcile_campaign(camp["id"], closed["version"])
    # Client still holds the pre-reconcile version (= reconciled.version - 1).
    res = api.disburse_campaign(
        camp["id"], {"expected_campaign_version": reconciled["version"] - 1}, TREASURER)
    validate_error(res, "ERR_STALE_CAMPAIGN_VERSION", expected_status=412)


def test_seller_block_cascade_releases_pending_order_reservation(api, admin_headers):
    """PRD §3.3: "Every `Order` crediting this seller that is still unpaid —
    `payment_status` equal to `PENDING` — and whose `fulfillment_status` is
    `PLACED` or `CONFIRMED` has its `fulfillment_status` driven to
    `CANCELLED`, and each such cancellation releases that order's product
    reservations so the affected products' `reserved_qty` recomputes
    downward."

    Design: Corner/cross_cutting_complexity_layers/seller_block_cascade_releases_pending_order_reservation
    """
    camp, seller, product = setup_active_catalog(stock_qty=50)
    order = place_simple_order(camp["id"], seller["id"], product["id"], 3)
    before = validate_success(api.get_product(product["id"], admin_headers), 200)
    assert before["reserved_qty"] == 3

    validate_success(api.block_seller(seller["id"], admin_headers), 200)
    after_order = validate_success(api.get_order(order["id"], admin_headers), 200)
    assert after_order["fulfillment_status"] == "CANCELLED"
    after_prod = validate_success(api.get_product(product["id"], admin_headers), 200)
    assert after_prod["reserved_qty"] == 0, \
        "block cascade must release the cancelled order's reservation"


def test_prize_tier_threshold_minus_one_not_earned(api):
    """PRD §3.6: "The boundary is inclusive: a `credited_cents` exactly equal to
    a tier's `threshold_cents` earns that tier, while a `credited_cents` one
    cent below does not. If no tier's threshold is at or below the seller's
    credit, `earned_prize_tier_id` is null"

    Design: Corner/cross_cutting_complexity_layers/prize_tier_threshold_minus_one_not_earned
    """
    # Single tier at 10826; one 5-unit order totalling 10825 (= threshold - 1).
    camp, seller, product = setup_active_catalog(prize_threshold_cents=10826)
    order = place_simple_order(camp["id"], seller["id"], product["id"], 5)  # total 10825
    api_client.pay_order(order["id"], ADMIN)
    after = validate_success(api_client.get_seller(seller["id"], TREASURER), 200)
    assert after["credited_cents"] == 10825
    assert after["earned_prize_tier_id"] is None, \
        "credited one cent below the only tier earns nothing"


# ─── consistency_model ─────────────────────────────────────────────────────

def test_order_pay_reflected_immediately_in_campaign_gross(api, treasurer_headers):
    """PRD §3.4: "the order's `total_charged_cents` now counts toward both the
    crediting seller's `credited_cents` and the campaign's
    `gross_collected_cents` (the settled view)"

    PRD §2.5: "fetching a campaign or its report recomputes
    `gross_collected_cents` and `forecast_gross_cents`"

    Design: Corner/consistency_model/order_pay_reflected_immediately_in_campaign_gross
    """
    camp, seller, product = setup_active_catalog()
    order = place_simple_order(camp["id"], seller["id"], product["id"], 5)  # total 10825
    api_client.pay_order(order["id"], ADMIN)
    fetched = validate_success(api.get_campaign(camp["id"], treasurer_headers), 200)
    assert fetched["gross_collected_cents"] == 10825, \
        "paying an order is immediately reflected in gross_collected_cents"
