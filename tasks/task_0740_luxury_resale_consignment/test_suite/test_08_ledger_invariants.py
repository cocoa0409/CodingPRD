"""Conserved-quantity invariants: the seller payout ledger under reversal and the
buyer purchase ledger under a buyer-favour return.
"""
from test_helpers import (
    assert_payout_ledger_conserved,
    # fixtures
    setup_delivered_sale, setup_delivered_sales_for_buyer,
    get_seller, get_buyer, get_sale, get_sale_payout,
    file_dispute, resolve_dispute,
)


# --- compensating_invariant: seller payout ledger conserved under reversal ---
def test_reversal_moves_pending_into_reversed(api):
    """PRD §3.8: "the sale's payout, whether it was `SCHEDULED` or `HELD`, moves to
    `REVERSED`, subtracting its `amount_cents` from the seller's `pending_payout_cents` and
    adding it to the seller's `reversed_payout_cents`."

    Design: Difficulty/compensating_invariant/seller_payout_ledger_conserved_under_reversal
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "not authentic")
    resolve_dispute(dispute["id"], "BUYER")
    seller = get_seller(ctx["seller_id"])
    assert seller["pending_payout_cents"] == 0, seller["pending_payout_cents"]
    assert seller["released_payout_cents"] == 0, seller["released_payout_cents"]
    assert seller["reversed_payout_cents"] == 144000, seller["reversed_payout_cents"]


def test_reversal_conserves_total_payout_quantity(api):
    """PRD §2.8: "Across all of a seller's payouts, the quantity `pending_payout_cents` +
    `released_payout_cents` + `reversed_payout_cents` is conserved and always equals the
    sum of `amount_cents` over every one of that seller's payouts: a reversal simply moves
    an amount out of the pending bucket and into the reversed bucket, leaving the conserved
    total unchanged."

    Design: Difficulty/compensating_invariant/seller_payout_ledger_conserved_under_reversal
    """
    ctx = setup_delivered_sale(list_price_cents=180000, category="HANDBAGS")
    dispute = file_dispute(ctx["sale_id"], ctx["buyer_id"], "AUTHENTICITY", "not authentic")
    resolve_dispute(dispute["id"], "BUYER")
    payout = get_sale_payout(ctx["sale_id"])
    seller = get_seller(ctx["seller_id"])
    assert payout["status"] == "REVERSED", payout["status"]
    # Q_payout = pending + released + reversed stays equal to the single payout's 144000.
    assert_payout_ledger_conserved(seller, 144000)


# --- compensating_invariant: buyer purchase ledger conserved under return ----
def test_buyer_return_subtracts_exact_order_total(api):
    """PRD §2.8: "Delivery adds a sale's `order_total_cents` to this total; a buyer-favour
    return subtracts exactly the same `order_total_cents`, so a sale that is delivered and
    later returned nets to zero contribution."

    Design: Difficulty/compensating_invariant/buyer_purchase_ledger_conserved_under_return
    """
    ctx = setup_delivered_sales_for_buyer(count=2, list_price_cents=180000, category="HANDBAGS")
    # Two delivered sales at order_total 214380 each -> lifetime 428760.
    sale_1 = ctx["sales"][0]
    dispute = file_dispute(sale_1["id"], ctx["buyer_id"], "CHANGE_OF_MIND", "returning one")
    resolve_dispute(dispute["id"], "BUYER")
    buyer = get_buyer(ctx["buyer_id"])
    # 428760 - 214380 = 214380 (exactly one order_total removed).
    assert buyer["lifetime_purchases_cents"] == 214380, buyer["lifetime_purchases_cents"]


def test_buyer_return_leaves_other_sale_delivered(api):
    """PRD §2.8: "`lifetime_purchases_cents`, which equals the sum of `order_total_cents`
    over that buyer's sales whose `fulfillment_status` is `DELIVERED` and is not
    `RETURNED`."

    Design: Difficulty/compensating_invariant/buyer_purchase_ledger_conserved_under_return
    """
    ctx = setup_delivered_sales_for_buyer(count=2, list_price_cents=180000, category="HANDBAGS")
    sale_1, sale_2 = ctx["sales"][0], ctx["sales"][1]
    dispute = file_dispute(sale_1["id"], ctx["buyer_id"], "CHANGE_OF_MIND", "returning one")
    resolve_dispute(dispute["id"], "BUYER")
    assert get_sale(sale_1["id"])["fulfillment_status"] == "RETURNED"
    assert get_sale(sale_2["id"])["fulfillment_status"] == "DELIVERED"
