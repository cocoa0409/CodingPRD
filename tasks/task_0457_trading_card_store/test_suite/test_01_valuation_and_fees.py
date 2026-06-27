"""Dual-variant and combinatorial money calculations: buylist payout (STORE_CREDIT
vs CASH), registration entry fee (provisional vs final), pre-order priority, and
consignment payout rounding order.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_customer, create_inventory_item, create_submitted_buylist,
    create_release_product, create_open_event, create_paid_registration,
    create_requested_pre_order, create_listed_consignment, set_clock,
    create_pre_order_payload, make_customer_headers,
    TEST_USERS,
)

SM = TEST_USERS["store_manager_headers"]


def test_buylist_store_credit_payout_uses_seventy_percent(api):
    """PRD §3.2: "that base is multiplied by a rate determined by the submission's
    payout method — 0.70 (70%) when the method is `STORE_CREDIT`, and 0.50 (50%)
    when the method is `CASH`; the result is rounded half-up to a whole number of
    cents and pinned as that line's `line_payout_cents`."
    PRD §3.2: "Finally, only when the payout method is `STORE_CREDIT`, acceptance
    appends a ledger row with `reason` `BUYLIST_PAYOUT` and `delta_cents` equal to
    the positive `offered_total_cents`, then recomputes the customer's balance"

    Design: Difficulty/dual_variant_calc/buylist_store_credit_vs_cash_payout
    """
    cust = create_customer("SC Buyer", "sc@x.com")
    item_a = create_inventory_item(title="Card A", market_price_cents=1000)
    item_b = create_inventory_item(title="Card B", market_price_cents=333)
    sub = create_submitted_buylist(cust, [(item_a, 3), (item_b, 1)],
                                   payout_method="STORE_CREDIT")
    accepted = validate_success(api.accept_buylist(sub["id"], SM), 200)
    # 1000*3*0.70 = 2100; 333*1*0.70 = 233.1 -> round half up 233; sum = 2333
    assert accepted["offered_total_cents"] == 2333
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 2333


def test_buylist_cash_payout_uses_fifty_percent_and_no_ledger(api):
    """PRD §3.2: "that base is multiplied by a rate determined by the submission's
    payout method — 0.70 (70%) when the method is `STORE_CREDIT`, and 0.50 (50%)
    when the method is `CASH`; the result is rounded half-up to a whole number of
    cents and pinned as that line's `line_payout_cents`."
    PRD §3.2: "when the method is `CASH`, no ledger row is appended because cash is
    handled out of band."

    Design: Difficulty/dual_variant_calc/buylist_store_credit_vs_cash_payout
    """
    cust = create_customer("Cash Buyer", "cash@x.com")
    item_a = create_inventory_item(title="Card A", market_price_cents=1000)
    item_b = create_inventory_item(title="Card B", market_price_cents=333)
    sub = create_submitted_buylist(cust, [(item_a, 3), (item_b, 1)],
                                   payout_method="CASH")
    accepted = validate_success(api.accept_buylist(sub["id"], SM), 200)
    # 1000*3*0.50 = 1500; 333*1*0.50 = 166.5 -> round half up 167; sum = 1667
    assert accepted["offered_total_cents"] == 1667
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 0


def test_registration_provisional_then_final_early_bird_fee(api):
    """PRD §3.4: "The provisional variant, computed at registration before the
    early-bird window is known, applies only the loyalty discount: the quoted fee
    is the base multiplied by one minus the loyalty fraction, rounded half-up to
    whole cents."
    PRD §3.4: "when early, an additional 1000 basis points (10%) is added to the
    loyalty discount fraction. The combined effective discount fraction is then
    capped so that it never exceeds 2000 basis points (20%); the charged fee is the
    base multiplied by one minus the capped effective fraction, rounded half-up to
    whole cents."

    Design: Difficulty/dual_variant_calc/registration_provisional_vs_final_fee
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Reg Cust", "reg@x.com", credit_cents=5000)
    ev = create_open_event(title="FNM", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=16,
                           entry_fee_cents=2000)
    reg = create_paid_registration(ev, cust)
    # BRONZE, no early-bird at registration: 2000 * (1 - 0) = 2000
    assert reg["quoted_fee_cents"] == 2000
    # Early-bird at check-in (>1 day out): 2000 * (1 - 0.10) = 1800
    checked = validate_success(api.check_in_registration(reg["id"], SM), 200)
    assert checked["charged_fee_cents"] == 1800


def test_preorder_priority_deposit_overrides_recency(api):
    """PRD §3.3: "The second is a deposit component: the deposit paid is divided by
    500 cents, the quotient is taken as a whole number (discarding any remainder),
    and that count of points is capped at a maximum of 30."
    PRD §3.3: "the component is 25 minus 5 for each rank position past the first —
    that is, 25 for rank 1, 20 for rank 2, and so on — but never less than 0. The
    three components are summed into `priority_score`; a higher score allocates
    first."

    Design: Difficulty/combinatorial_formula/preorder_priority_three_input_nonlinear
    """
    c1 = create_customer("PO1 Cust", "po1@x.com", credit_cents=6000)
    c2 = create_customer("PO2 Cust", "po2@x.com", credit_cents=6000)
    rp = create_release_product(title="Booster Box", allocation_pool=100,
                                unit_price_cents=9000, deposit_required_cents=1000)
    # PO1 first (rank 1, deposit 1000): tier 0 + deposit min(30, 1000//500=2)=2 + recency 25 = 27
    po1 = create_requested_pre_order(c1, rp, requested_quantity=1, deposit_paid_cents=1000)
    # PO2 second (rank 2, deposit 5000): tier 0 + deposit min(30, 5000//500=10)=10 + recency 20 = 30
    po2 = create_requested_pre_order(c2, rp, requested_quantity=1, deposit_paid_cents=5000)
    assert po1["priority_score"] == 27
    assert po2["priority_score"] == 30


def test_consignment_payout_rounds_per_unit_then_multiplies(api):
    """PRD §3.7: "the per-unit commission is the `ask_price_cents` multiplied by the
    `commission_rate_bps` divided by 10000, rounded half-up to whole cents; the
    per-unit net is the ask price minus that per-unit commission; and
    `payout_total_cents` is the per-unit net multiplied by the case `quantity`."
    PRD §3.7: "The order is fixed — commission is rounded per unit first, and the
    multiplication by quantity happens afterward — because computing commission on
    the full gross and rounding once would yield a different cent total."

    Design: Difficulty/combinatorial_formula/consignment_round_per_unit_then_multiply
    """
    cust = create_customer("Consignor", "cons@x.com")
    item = create_inventory_item(title="Bulk Common", market_price_cents=10)
    cc = create_listed_consignment(cust, item, quantity=7, ask_price_cents=10,
                                   commission_rate_bps=1500)
    sold = validate_success(api.sell_consignment_case(cc["id"], SM), 200)
    # per-unit commission round_half_up(10*0.15=1.5)=2; net 8; total 8*7 = 56
    assert sold["payout_total_cents"] == 56
