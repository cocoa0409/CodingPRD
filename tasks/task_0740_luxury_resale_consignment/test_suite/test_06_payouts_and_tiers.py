"""Payout settlement, the inclusive PREMIER tier boundary, and payout-release guards.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
    # fixtures
    setup_delivered_sale, get_seller, file_dispute, set_clock,
)

_ADMIN = TEST_USERS["ops_admin_headers"]


# --- boundary_precision_check: release to exactly the PREMIER threshold -------
def test_release_to_exact_premier_threshold_upgrades_tier(api):
    """PRD §3.7: "On release, the server stamps `released_at` with the current clock and
    adjusts the seller's ledger: it subtracts the payout's `amount_cents` from
    `pending_payout_cents`, adds it to `released_payout_cents`, and adds it to
    `lifetime_net_sales_cents`."
    PRD §3.7: "Because the boundary is inclusive, a seller sitting exactly at 1,000,000
    cents is `PREMIER`, while one at 999,999 cents remains `STANDARD`."

    Design: Difficulty/boundary_precision_check/tier_upgrade_at_exact_premier_threshold
    """
    # net = 1250000 - round(1250000*0.20)=250000 -> 1000000; delivered 2026-03-10,
    # window ends 2026-03-24, scheduled_release 2026-03-25.
    ctx = setup_delivered_sale(list_price_cents=1250000, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-25T00:00:00Z")
    validate_success(api.release_payout(ctx["payout_id"], _ADMIN), 200)
    seller = get_seller(ctx["seller_id"])
    assert seller["lifetime_net_sales_cents"] == 1000000, seller["lifetime_net_sales_cents"]
    assert seller["tier"] == "PREMIER", seller["tier"]


def test_release_moves_amount_from_pending_to_released(api):
    """PRD §3.7: "it subtracts the payout's `amount_cents` from `pending_payout_cents`,
    adds it to `released_payout_cents`, and adds it to `lifetime_net_sales_cents`."

    Design: Difficulty/boundary_precision_check/tier_upgrade_at_exact_premier_threshold
    """
    ctx = setup_delivered_sale(list_price_cents=1250000, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-25T00:00:00Z")
    validate_success(api.release_payout(ctx["payout_id"], _ADMIN), 200)
    seller = get_seller(ctx["seller_id"])
    assert seller["released_payout_cents"] == 1000000, seller["released_payout_cents"]
    assert seller["pending_payout_cents"] == 0, seller["pending_payout_cents"]


# --- Corner: one below threshold stays STANDARD ------------------------------
def test_release_one_below_threshold_stays_standard(api):
    """PRD §3.7: "Because the boundary is inclusive, a seller sitting exactly at 1,000,000
    cents is `PREMIER`, while one at 999,999 cents remains `STANDARD`."

    Design: Corner/calculations/tier_stays_standard_one_below_premier_threshold
    """
    # net = 1249999 - round(1249999*0.20=249999.8 -> 250000) = 999999.
    ctx = setup_delivered_sale(list_price_cents=1249999, category="HANDBAGS",
                               delivered_clock="2026-03-10T00:00:00Z")
    set_clock("2026-03-25T00:00:00Z")
    validate_success(api.release_payout(ctx["payout_id"], _ADMIN), 200)
    seller = get_seller(ctx["seller_id"])
    assert seller["lifetime_net_sales_cents"] == 999999, seller["lifetime_net_sales_cents"]
    assert seller["tier"] == "STANDARD", seller["tier"]


# --- Corner: HELD payout cannot be released ----------------------------------
def test_release_held_payout_rejected(api):
    """PRD §3.7: "The payout must be in `SCHEDULED` status: a payout that a filed dispute
    has already moved to `HELD` (or that is already `RELEASED` or `REVERSED`) is rejected
    with `ERR_PAYOUT_NOT_RELEASABLE` (HTTP 409)."

    Design: Corner/state_machines/release_held_payout_returns_not_releasable
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    # Filing a dispute cascades the SCHEDULED payout to HELD (PRD §3.8).
    file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "hold it")
    res = api.release_payout(ctx["payout_id"], _ADMIN)
    validate_error(res, "ERR_PAYOUT_NOT_RELEASABLE", expected_status=409)


# --- Corner: release before scheduled_release_at -----------------------------
def test_release_before_scheduled_release_rejected(api):
    """PRD §3.7: "And the current logical clock must have reached the
    `scheduled_release_at` instant — release attempted before that instant is rejected
    with `ERR_PAYOUT_HOLD_ACTIVE` (HTTP 409)."

    Design: Corner/validations/release_before_scheduled_returns_hold_active
    """
    # Delivered at the default clock (2026-03-01); scheduled_release is later, clock unchanged.
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    res = api.release_payout(ctx["payout_id"], _ADMIN)
    validate_error(res, "ERR_PAYOUT_HOLD_ACTIVE", expected_status=409)


# --- Corner: payout discoverable via the sale sub-resource -------------------
def test_delivered_sale_payout_reachable_via_subresource(api):
    """PRD §3.6: "It creates a `Payout` for the seller in `SCHEDULED` status, whose
    `amount_cents` equals the sale's `seller_net_payout_cents`"
    PRD §2.9: "The payouts and disputes belonging to a sale are retrieved as sub-resource
    lists under that sale, giving reverse reachability from a `Sale` to its `Payout`
    records (by `sale_id`) and its `Dispute` records (by `sale_id`)."

    Design: Corner/endpoints/payout_reverse_reachable_via_sale_subresource
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    data, _meta = validate_paginated(api.list_sale_payouts(ctx["sale_id"], _ADMIN))
    assert len(data) == 1, len(data)
    payout = data[0]
    assert payout["status"] == "SCHEDULED", payout["status"]
    # net = 180000 - round(180000*0.20)=36000 -> 144000.
    assert payout["amount_cents"] == 144000, payout["amount_cents"]
