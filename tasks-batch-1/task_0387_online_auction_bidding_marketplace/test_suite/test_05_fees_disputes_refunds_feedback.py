"""Seller fees, disputes, refunds, returns, feedback, and the cascades among them.

Each test translates exactly one design-index instance. Difficulty instances each
receive at least two tests.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    register_seller, register_buyer,
    set_clock, advance_clock,
    setup_bought_order, setup_paid_order, setup_shipped_order,
    setup_delivered_order, setup_escalated_dispute, setup_suspended_seller,
    setup_published_buy_now, buy_now_order,
    pay_order, ship_order, deliver_order,
    get_invoice_for_order, open_dispute,
)
from test_helpers.api_client import api_client

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _invoice_for(order_id):
    return get_invoice_for_order(order_id)


# ════════════════════════════════════════════════════════════════════
# Difficulty: seller_fee_full_credit_vs_partial_recompute_on_order (>=2)
# ════════════════════════════════════════════════════════════════════

def test_partial_refund_recomputes_fee_on_reduced_gross(api):
    """PRD §3.10: "A partial refund — where the refunded amount is greater than zero but
    strictly less than the order's paid_amount_cents — appends a REFUND payment event for the
    refunded amount, subtracts that amount from paid_amount_cents, moves payment_status to
    PARTIALLY_REFUNDED, and recomputes the seller fee invoice's amount_cents against the
    reduced gross (the fee is adjusted on the smaller base, not fully credited)."

    Design: Difficulty/dual_variant_calc/seller_fee_full_credit_vs_partial_recompute_on_order
    """
    # Item 30000, pay 30000, partial refund 10000 -> reduced gross 20000.
    # Fee on 20000: 20000 * 0.1255 = 2510.0 exact -> 2510 + 30 = 2540.
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=30000, requested_amount_cents=10000)
    validate_success(api.resolve_dispute(dispute["id"], {"approved_amount_cents": 10000},
                                         ADMIN), 200)

    order_after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert order_after["payment_status"] == "PARTIALLY_REFUNDED"
    assert order_after["paid_amount_cents"] == 20000

    invoice = _invoice_for(order["id"])
    assert invoice["amount_cents"] == 2540
    assert invoice["settlement_status"] == "INVOICED"


def test_full_refund_credits_invoice_to_zero_effective(api):
    """PRD §3.10: "A full refund — where the refunded amount equals the order's
    paid_amount_cents — appends a Payment event of kind REFUND for the full prior paid
    amount, sets paid_amount_cents to 0 (preserving the conserved-quantity invariant), moves
    payment_status to REFUNDED, and credits the order's seller fee invoice."

    Design: Difficulty/dual_variant_calc/seller_fee_full_credit_vs_partial_recompute_on_order
    """
    # Item 30000, pay 30000, full refund of 30000 -> invoice CREDITED.
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=30000, requested_amount_cents=30000)
    validate_success(api.resolve_dispute(dispute["id"], {"approved_amount_cents": 30000},
                                         ADMIN), 200)

    order_after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert order_after["payment_status"] == "REFUNDED"
    assert order_after["paid_amount_cents"] == 0

    invoice = _invoice_for(order["id"])
    assert invoice["settlement_status"] == "CREDITED"


# ════════════════════════════════════════════════════════════════════
# Difficulty: account_feedback_score_net_vs_seller_fee_balance_outstanding (>=2)
# ════════════════════════════════════════════════════════════════════

def test_feedback_score_net_and_fee_balance_disjoint(api):
    """PRD §3.1: "The feedback_score of an account is its net reputation: the count of
    Feedback rows where that account is the ratee_account_id and the rating is POSITIVE,
    minus the count of rows where it is the ratee and the rating is NEGATIVE."
    PRD §2.8: "The fee_balance_cents field on an Account is the sum of the amount_cents of all
    that seller's SellerFeeInvoice records whose settlement_status is INVOICED"

    Design: Difficulty/dual_variant_calc/account_feedback_score_net_vs_seller_fee_balance_outstanding
    """
    # Seller sells 30000 (invoice 3630 INVOICED), order delivered.
    seller = register_seller()
    buyer = register_buyer()
    set_clock("2026-06-01T00:00:00Z")
    from test_helpers import create_and_publish_listing
    listing = create_and_publish_listing(seller["id"], format="BUY_NOW",
                                         buy_now_price_cents=30000)
    order = buy_now_order(listing["id"], buyer["id"], shipping_cents=0)
    order = pay_order(order, buyer["id"])
    order = ship_order(order["id"], seller["id"])
    order = deliver_order(order["id"], buyer["id"])
    # Seller leaves NEGATIVE on buyer; buyer leaves POSITIVE on seller.
    validate_success(api.create_feedback(order["id"],
                                         {"rater_account_id": seller["id"], "rating": "NEGATIVE"},
                                         make_seller_headers(seller["id"])), 201)
    validate_success(api.create_feedback(order["id"],
                                         {"rater_account_id": buyer["id"], "rating": "POSITIVE"},
                                         make_buyer_headers(buyer["id"])), 201)

    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    b_acct = validate_success(api.get_account(buyer["id"], ANON), 200)
    assert s_acct["feedback_score"] == 1
    assert s_acct["fee_balance_cents"] == 3630
    assert b_acct["feedback_score"] == -1


def test_neutral_feedback_contributes_zero_to_score(api):
    """PRD §3.1: "A NEUTRAL rating contributes zero. There is no time window — the score is a
    lifetime tally — and it is recomputed in full from all of the ratee's feedback rows each
    time a new feedback is created."

    Design: Difficulty/dual_variant_calc/account_feedback_score_net_vs_seller_fee_balance_outstanding
    """
    seller, buyer, listing, order = setup_delivered_order(
        buy_now_price_cents=20000, shipping_cents=0, deliver_at="2026-06-02T00:00:00Z")
    # Buyer rates seller NEUTRAL -> seller feedback_score unchanged (0).
    validate_success(api.create_feedback(order["id"],
                                         {"rater_account_id": buyer["id"], "rating": "NEUTRAL"},
                                         make_buyer_headers(buyer["id"])), 201)
    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["feedback_score"] == 0


# ════════════════════════════════════════════════════════════════════
# Difficulty: seller_fee_sum_then_round_order_pinned (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_seller_fee_sum_then_round_30000(api):
    """PRD §3.7: "the rounding order is pinned to sum-then-round, meaning all of the exact
    tier products are summed first and only the resulting total is rounded half-up to a whole
    number of cents — never rounded tier by tier. The flat insertion fee of 30 cents is then
    added to that rounded value."

    Design: Difficulty/combinatorial_formula/seller_fee_sum_then_round_order_pinned
    """
    # Gross 30000: tier1 25000*0.1255=3137.5 ; tier2 5000*0.0925=462.5 ; sum 3600.0
    # sum-then-round = 3600 + 30 = 3630 (NOT 3601 + 30 = 3631).
    seller, buyer, listing = setup_published_buy_now(buy_now_price_cents=30000)
    order = buy_now_order(listing["id"], buyer["id"], shipping_cents=0)
    invoice = _invoice_for(order["id"])
    assert invoice["amount_cents"] == 3630
    assert invoice["gross_item_cents"] == 30000


def test_seller_fee_three_tier_sum_then_round(api):
    """PRD §3.7: "The slice from 0 up to 25000 cents is charged at 1255 basis points (12.55
    percent). The slice from 25000 cents up to 75000 cents is charged at 925 basis points
    (9.25 percent). Any portion above 75000 cents is charged at 255 basis points (2.55
    percent)."

    Design: Difficulty/combinatorial_formula/seller_fee_sum_then_round_order_pinned
    """
    # Gross 100000: t1 25000*0.1255=3137.5 ; t2 50000*0.0925=4625.0 ; t3 25000*0.0255=637.5
    # sum = 8400.0 -> round = 8400 + 30 = 8430.
    seller, buyer, listing = setup_published_buy_now(buy_now_price_cents=100000)
    order = buy_now_order(listing["id"], buyer["id"], shipping_cents=0)
    invoice = _invoice_for(order["id"])
    assert invoice["amount_cents"] == 8430
    assert invoice["gross_item_cents"] == 100000


# ════════════════════════════════════════════════════════════════════
# Corner: seller_fee_cap_applied
# ════════════════════════════════════════════════════════════════════

def test_seller_fee_cap_applied(api):
    """PRD §3.7: "Finally the total is capped: the fee owed is the smaller of the computed
    total and the fee cap of 75000 cents."

    Design: Corner/calculations/seller_fee_cap_applied
    """
    seller, buyer, listing = setup_published_buy_now(buy_now_price_cents=4000000)
    order = buy_now_order(listing["id"], buyer["id"], shipping_cents=0)
    invoice = _invoice_for(order["id"])
    assert invoice["amount_cents"] == 75000


# ════════════════════════════════════════════════════════════════════
# Difficulty: auction_close_cascade_order_invoice_balance (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_auction_close_cascades_order_invoice_balance(api):
    """PRD §2.5: "When an auction closes with a met reserve ... the platform does not merely
    change the listing's status — it mints an Order and, from that order, raises a
    SellerFeeInvoice, a depth-three chain that must complete in full."
    PRD §2.8: "This balance is recomputed every time an invoice is created, settled,
    credited, or otherwise recomputed."

    Design: Difficulty/transitive_cascade/auction_close_cascade_order_invoice_balance
    """
    from test_helpers import setup_published_auction, place_bid
    seller, listing = setup_published_auction(
        start_price_cents=10000, reserve_price_cents=18000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    place_bid(listing["id"], a["id"], 30000)   # first -> 10000
    place_bid(listing["id"], b["id"], 20000)   # A retains lead at 20500 (>= reserve 18000)
    advance_clock("2026-06-10T00:00:01Z")

    lst = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert lst["status"] == "SOLD"
    assert lst["sold_price_cents"] == 20500
    assert lst["winner_account_id"] == a["id"]

    # Find the order via reverse lookup, then its invoice.
    orders, _meta = validate_paginated(
        api.list_orders(make_seller_headers(seller["id"]),
                        params={"listing_id": listing["id"]}))
    order = orders[0]
    assert order["item_price_cents"] == 20500
    # Fee on 20500: t1 20500*0.1255=2572.75 exact -> round 2573 + 30 = 2603.
    invoice = _invoice_for(order["id"])
    assert invoice["amount_cents"] == 2603

    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["fee_balance_cents"] == 2603


def test_auction_close_met_creates_order_sold(api):
    """PRD §3.6: "the listing moves through ENDED_MET — a transient bridge state — setting
    winner_account_id to the winning bid's bidder_account_id and sold_price_cents to the
    winning bid's current_price_cents, then cascading to create an Order with source of
    AUCTION_WIN whose item_price_cents is the sold price, which in turn cascades a seller fee
    invoice; once that order exists the listing continues to SOLD."

    Design: Difficulty/transitive_cascade/auction_close_cascade_order_invoice_balance
    """
    from test_helpers import setup_published_auction, place_bid
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    place_bid(listing["id"], a["id"], 15000)   # first -> 10000, no reserve
    advance_clock("2026-06-10T00:00:01Z")

    lst = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert lst["status"] == "SOLD"
    assert lst["winner_account_id"] == a["id"]
    assert lst["sold_price_cents"] == 10000

    orders, _ = validate_paginated(
        api.list_orders(make_seller_headers(seller["id"]),
                        params={"listing_id": listing["id"]}))
    assert len(orders) == 1
    assert orders[0]["source"] == "AUCTION_WIN"
    assert orders[0]["item_price_cents"] == 10000


# ════════════════════════════════════════════════════════════════════
# Difficulty: order_cancel_cascade_invoice_credit_balance (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_order_cancel_credits_invoice_and_zeroes_balance(api):
    """PRD §3.8: "Cancellation moves fulfillment_status to CANCELLED, credits the order's
    seller fee invoice (no sale occurred, so the fee is reversed), and cancels the
    originating listing if it is not already terminal."
    PRD §2.8: "This balance is recomputed every time an invoice is created, settled,
    credited, or otherwise recomputed."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_invoice_credit_balance
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=30000, shipping_cents=0)
    s_before = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_before["fee_balance_cents"] == 3630

    validate_success(api.cancel_order(order["id"], make_seller_headers(seller["id"])), 200)

    order_after = validate_success(api.get_order(order["id"], make_seller_headers(seller["id"])), 200)
    assert order_after["fulfillment_status"] == "CANCELLED"
    invoice = _invoice_for(order["id"])
    assert invoice["settlement_status"] == "CREDITED"
    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["fee_balance_cents"] == 0


# ════════════════════════════════════════════════════════════════════
# Difficulty: return_window_buffered_interval_exclusive (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_complete_return_after_window_rejected(api):
    """PRD §3.9: "Completing a return is permitted only while the fulfillment_status is
    DELIVERED and the current clock is at most the return window of 14 days (1209600 seconds)
    past the time the order reached DELIVERED; a return completed after that window is refused
    with ERR_WINDOW_EXPIRED."

    Design: Difficulty/resource_temporal_overlap/return_window_buffered_interval_exclusive
    """
    seller, buyer, listing, order = setup_delivered_order(
        buy_now_price_cents=20000, shipping_cents=0, deliver_at="2026-06-02T00:00:00Z")
    advance_clock("2026-06-17T00:00:00Z")   # 15 days after delivery, past 14d window

    res = api.complete_return(order["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_WINDOW_EXPIRED", expected_status=409)
    after = validate_success(api.get_order(order["id"], make_seller_headers(seller["id"])), 200)
    assert after["fulfillment_status"] == "DELIVERED"
    assert after["payment_status"] == "PAID"


def test_complete_return_within_window_succeeds(api):
    """PRD §3.9: "A completed return moves fulfillment_status to RETURNED and cascades a full
    refund: the payment_status moves to REFUNDED with the full paid_amount_cents returned, and
    the order's seller fee invoice is credited."

    Design: Difficulty/resource_temporal_overlap/return_window_buffered_interval_exclusive
    """
    seller, buyer, listing, order = setup_delivered_order(
        buy_now_price_cents=20000, shipping_cents=0, deliver_at="2026-06-02T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")   # 8 days after delivery, inside window

    returned = validate_success(
        api.complete_return(order["id"], make_seller_headers(seller["id"])), 200)
    assert returned["fulfillment_status"] == "RETURNED"
    assert returned["payment_status"] == "REFUNDED"


# ════════════════════════════════════════════════════════════════════
# Difficulty: full_refund_conserves_paid_amount_to_zero (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_return_full_refund_conserves_paid_amount_to_zero(api):
    """PRD §3.10: "A full refund — where the refunded amount equals the order's
    paid_amount_cents — appends a Payment event of kind REFUND for the full prior paid amount,
    sets paid_amount_cents to 0 (preserving the conserved-quantity invariant), moves
    payment_status to REFUNDED, and credits the order's seller fee invoice."

    Design: Difficulty/compensating_invariant/full_refund_conserves_paid_amount_to_zero
    """
    seller, buyer, listing, order = setup_delivered_order(
        buy_now_price_cents=20000, shipping_cents=0, deliver_at="2026-06-02T00:00:00Z")
    validate_success(api.complete_return(order["id"], make_seller_headers(seller["id"])), 200)

    after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert after["paid_amount_cents"] == 0
    assert after["payment_status"] == "REFUNDED"
    assert after["fulfillment_status"] == "RETURNED"


def test_dispute_full_refund_conserves_paid_amount_to_zero(api):
    """PRD §3.10: "A full refund — where the refunded amount equals the order's
    paid_amount_cents — appends a Payment event of kind REFUND for the full prior paid amount,
    sets paid_amount_cents to 0 (preserving the conserved-quantity invariant), moves
    payment_status to REFUNDED, and credits the order's seller fee invoice."

    Design: Difficulty/compensating_invariant/full_refund_conserves_paid_amount_to_zero
    """
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=20000, requested_amount_cents=20000)
    validate_success(api.resolve_dispute(dispute["id"], {"approved_amount_cents": 20000},
                                         ADMIN), 200)
    after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert after["paid_amount_cents"] == 0
    assert after["payment_status"] == "REFUNDED"


# ════════════════════════════════════════════════════════════════════
# Difficulty: order_cancel_conserves_fee_balance_to_zero (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_order_cancel_conserves_fee_balance_to_zero(api):
    """PRD §2.8: "The fee_balance_cents is a conserved-quantity anchor: it always equals the
    sum of outstanding invoices and is never edited directly."
    PRD §3.7: "the system credits an invoice — moving settlement_status from INVOICED to
    CREDITED — whenever the underlying sale is unwound: when the order is cancelled before
    payment, when its payment is fully refunded, or when a return is completed."

    Design: Difficulty/compensating_invariant/order_cancel_conserves_fee_balance_to_zero
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=30000, shipping_cents=0)
    validate_success(api.cancel_order(order["id"], make_seller_headers(seller["id"])), 200)

    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["fee_balance_cents"] == 0
    invoice = _invoice_for(order["id"])
    assert invoice["settlement_status"] == "CREDITED"


def test_order_cancel_restores_good_standing(api):
    """PRD §2.8: "the standing is GOOD when fee_balance_cents is less than or equal to the
    suspension threshold of 3000 cents"
    PRD §3.7: "Crediting likewise recomputes the seller's fee_balance_cents (the credited
    invoice contributes zero) and standing"

    Design: Difficulty/compensating_invariant/order_cancel_conserves_fee_balance_to_zero
    """
    # Sale of 30000 -> fee 3630 -> SUSPENDED; cancel -> CREDITED -> balance 0 -> GOOD.
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=30000, shipping_cents=0)
    s_before = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_before["standing"] == "SUSPENDED"

    validate_success(api.cancel_order(order["id"], make_seller_headers(seller["id"])), 200)
    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["standing"] == "GOOD"


# ════════════════════════════════════════════════════════════════════
# Corner: dispute_branch_no_refund_leaves_payment_unchanged
# ════════════════════════════════════════════════════════════════════

def test_dispute_no_refund_branch_leaves_payment_unchanged(api):
    """PRD §3.10: "If the approved amount is exactly zero, the dispute moves to
    RESOLVED_NO_REFUND, its resolved_amount_cents stays 0, and the order's payment and the
    seller's fee invoice are left untouched."

    Design: Corner/state_machines/dispute_branch_no_refund_leaves_payment_unchanged
    """
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=20000, requested_amount_cents=5000, reason="DAMAGED")
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], {"approved_amount_cents": 0}, ADMIN), 200)
    assert resolved["status"] == "RESOLVED_NO_REFUND"
    assert resolved["resolved_amount_cents"] == 0

    order_after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert order_after["payment_status"] == "PAID"
    assert order_after["paid_amount_cents"] == 20000


# ════════════════════════════════════════════════════════════════════
# Corner: settle_invoice_clears_fee_balance_restores_standing
# ════════════════════════════════════════════════════════════════════

def test_settle_invoice_clears_balance_restores_standing(api):
    """PRD §3.7: "A PlatformAdmin may settle an outstanding invoice, moving its
    settlement_status from INVOICED to PAID. Settling recomputes the seller's
    fee_balance_cents (the now-paid invoice contributes zero) and the seller's standing"

    Design: Corner/state_machines/settle_invoice_clears_fee_balance_restores_standing
    """
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=30000, shipping_cents=0)
    invoice = _invoice_for(order["id"])
    assert invoice["settlement_status"] == "INVOICED"

    settled = validate_success(api.settle_invoice(invoice["id"], ADMIN), 200)
    assert settled["settlement_status"] == "PAID"

    s_acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert s_acct["fee_balance_cents"] == 0
    assert s_acct["standing"] == "GOOD"


# ════════════════════════════════════════════════════════════════════
# Corner: feedback_before_delivery_rejected
# ════════════════════════════════════════════════════════════════════

def test_feedback_before_delivery_rejected(api):
    """PRD §3.11: "Feedback may be left only when the order's fulfillment_status is DELIVERED
    or RETURNED, the rater must be either the buyer or the seller of the order, and there may
    be at most one feedback per order per role; a violation is refused with
    ERR_FEEDBACK_NOT_ELIGIBLE."

    Design: Corner/validations/feedback_before_delivery_rejected
    """
    seller, buyer, listing, order = setup_shipped_order(
        buy_now_price_cents=20000, shipping_cents=0)
    res = api.create_feedback(order["id"],
                              {"rater_account_id": buyer["id"], "rating": "POSITIVE"},
                              make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_FEEDBACK_NOT_ELIGIBLE", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Corner: feedback_duplicate_role_rejected
# ════════════════════════════════════════════════════════════════════

def test_feedback_duplicate_role_rejected(api):
    """PRD §3.11: "there may be at most one feedback per order per role; a violation is
    refused with ERR_FEEDBACK_NOT_ELIGIBLE."
    PRD §3.11: "The uniqueness constraint is on the pair of order_id and role."

    Design: Corner/validations/feedback_duplicate_role_rejected
    """
    seller, buyer, listing, order = setup_delivered_order(
        buy_now_price_cents=20000, shipping_cents=0, deliver_at="2026-06-02T00:00:00Z")
    validate_success(api.create_feedback(order["id"],
                                         {"rater_account_id": buyer["id"], "rating": "POSITIVE"},
                                         make_buyer_headers(buyer["id"])), 201)
    res = api.create_feedback(order["id"],
                              {"rater_account_id": buyer["id"], "rating": "NEGATIVE"},
                              make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_FEEDBACK_NOT_ELIGIBLE", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Corner: dispute_escalate_before_response_window_rejected
# ════════════════════════════════════════════════════════════════════

def test_dispute_escalate_before_response_window_rejected(api):
    """PRD §3.10: "a buyer may escalate an OPEN dispute only after the seller-response window
    of 72 hours (259200 seconds) has elapsed since the dispute's created_at; an escalation
    attempted before that interval has passed is refused with ERR_WINDOW_EXPIRED."

    Design: Corner/validations/dispute_escalate_before_response_window_rejected
    """
    seller, buyer, listing, order = setup_paid_order(
        buy_now_price_cents=20000, shipping_cents=0)
    dispute = open_dispute(order["id"], buyer["id"], reason="DAMAGED",
                           requested_amount_cents=1000)
    advance_clock("2026-06-01T01:00:00Z")   # only +1h since opening

    res = api.escalate_dispute(dispute["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_WINDOW_EXPIRED", expected_status=409)
    after = validate_success(api.get_dispute(dispute["id"], make_buyer_headers(buyer["id"])), 200)
    assert after["status"] == "OPEN"


# ════════════════════════════════════════════════════════════════════
# Corner: resolve_refund_exceeds_paid_rejected
# ════════════════════════════════════════════════════════════════════

def test_resolve_refund_exceeds_paid_rejected(api):
    """PRD §3.10: "The approved amount must not exceed the order's paid_amount_cents; an
    approved amount greater than the paid amount is refused with ERR_REFUND_EXCEEDS_PAID."

    Design: Corner/validations/resolve_refund_exceeds_paid_rejected
    """
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=20000, requested_amount_cents=20000, reason="DAMAGED")
    res = api.resolve_dispute(dispute["id"], {"approved_amount_cents": 25000}, ADMIN)
    validate_error(res, "ERR_REFUND_EXCEEDS_PAID", expected_status=422)
    order_after = validate_success(api.get_order(order["id"], make_buyer_headers(buyer["id"])), 200)
    assert order_after["payment_status"] == "PAID"


# ════════════════════════════════════════════════════════════════════
# Corner: seller_cannot_resolve_dispute
# ════════════════════════════════════════════════════════════════════

def test_seller_cannot_resolve_dispute(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/roles/seller_cannot_resolve_dispute
    """
    seller, buyer, listing, order, dispute = setup_escalated_dispute(
        buy_now_price_cents=20000, requested_amount_cents=1000, reason="DAMAGED")
    res = api.resolve_dispute(dispute["id"], {"approved_amount_cents": 1000},
                              make_seller_headers(seller["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
