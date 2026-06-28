"""Transitive cascades (event-cancel refund depth-3, buylist-accept inventory+credit
depth-2) and compensating invariants (buylist void restores inventory units,
pay+refund conserves store credit).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_customer, create_inventory_item, create_submitted_buylist,
    create_open_event, create_paid_registration, set_clock,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]


# ─── transitive_cascade (difficulty) ────────────────────────────────────────────
def test_event_cancel_refunds_paid_registration_depth3(api):
    """PRD §3.5: "Every non-`WITHDRAWN` registration on the event has its
    `checkin_status` set to `WITHDRAWN`; and any such registration whose
    `payment_status` is `PAID` is driven to `REFUNDED`, which in turn appends an
    `EVENT_REFUND` ledger row and recomputes that customer's
    `store_credit_balance_cents`."

    Design: Difficulty/transitive_cascade/event_cancel_refund_ledger_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Cancel Cust", "cc@x.com", credit_cents=5000)
    ev = create_open_event(title="Doomed Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    reg = create_paid_registration(ev, cust)  # quoted 2000, balance now 3000
    cancelled = validate_success(api.cancel_event(ev["id"], SM), 200)
    assert cancelled["status"] == "CANCELLED"
    reg_after = validate_success(api.get_registration(reg["id"], SM), 200)
    assert reg_after["payment_status"] == "REFUNDED"
    assert reg_after["checkin_status"] == "WITHDRAWN"
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    # 5000 grant - 2000 charge + 2000 refund = 5000
    assert cust_after["store_credit_balance_cents"] == 5000


def test_buylist_accept_bumps_inventory_and_credits_depth2(api):
    """PRD §3.2: "Beyond valuation, acceptance adds each accepted line's quantity to
    the mapped inventory item's `quantity_on_hand`."
    PRD §3.2: "only when the payout method is `STORE_CREDIT`, acceptance appends a
    ledger row with `reason` `BUYLIST_PAYOUT` and `delta_cents` equal to the positive
    `offered_total_cents`, then recomputes the customer's balance"

    Design: Difficulty/transitive_cascade/buylist_accept_inventory_and_credit_depth2
    """
    cust = create_customer("Seller", "seller@x.com")
    item = create_inventory_item(title="Hot Card", market_price_cents=1000)
    sub = create_submitted_buylist(cust, [(item, 3)], payout_method="STORE_CREDIT")
    accepted = validate_success(api.accept_buylist(sub["id"], SM), 200)
    # 1000 * 3 * 0.70 = 2100
    assert accepted["offered_total_cents"] == 2100
    item_after = validate_success(api.get_inventory_item(item["id"], SM), 200)
    assert item_after["quantity_on_hand"] == 3
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 2100


# ─── compensating_invariant (difficulty) ────────────────────────────────────────
def test_buylist_void_restores_inventory_units(api):
    """PRD §3.2: "each line's quantity is subtracted back out of the item's
    `quantity_on_hand`, restoring the inventory-units invariant. If the original
    payout method was `STORE_CREDIT`, the void appends a compensating ledger row
    with `reason` `BUYLIST_PAYOUT` and `delta_cents` equal to the negated
    `offered_total_cents`, then recomputes the balance, restoring the store-credit
    invariant; the net store-credit effect of an accept-then-void pair is zero."

    Design: Difficulty/compensating_invariant/buylist_void_restores_inventory_units
    """
    cust = create_customer("Void Seller", "void@x.com")
    item = create_inventory_item(title="Reversible Card", market_price_cents=1000)
    sub = create_submitted_buylist(cust, [(item, 3)], payout_method="STORE_CREDIT")
    validate_success(api.accept_buylist(sub["id"], SM), 200)  # on_hand 3, credit 2100
    voided = validate_success(api.void_buylist(sub["id"], SM), 200)
    assert voided["status"] == "VOIDED"
    item_after = validate_success(api.get_inventory_item(item["id"], SM), 200)
    assert item_after["quantity_on_hand"] == 0
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 0


def test_pay_then_withdraw_conserves_store_credit(api):
    """PRD §3.4: "If the registration's payment status is `PAID` at the time of
    withdrawal, withdrawing also drives the payment dimension from `PAID` to
    `REFUNDED`."
    PRD §3.4: "it appends a ledger row with `reason` `EVENT_REFUND` whose
    `delta_cents` is the positive `charged_fee_cents` if the registration was checked
    in, or the positive `quoted_fee_cents` if it was not, and then recomputes the
    customer's balance. The pay-then-refund pair is designed to net to zero
    store-credit movement."

    Design: Difficulty/compensating_invariant/registration_pay_refund_conserves_store_credit
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("RefundCust", "refund@x.com", credit_cents=5000)
    ev = create_open_event(title="Refundable Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    reg = create_paid_registration(ev, cust)  # pay debits 2000 -> balance 3000
    cust_h = make_customer_headers(cust["id"])
    withdrawn = validate_success(api.withdraw_registration(reg["id"], cust_h), 200)
    assert withdrawn["payment_status"] == "REFUNDED"
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 5000
