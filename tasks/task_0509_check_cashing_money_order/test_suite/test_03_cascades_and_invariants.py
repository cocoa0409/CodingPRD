"""Depth tests on transitive cascades (return depth-3, void depth-2) and
compensating-action invariants on drawer cash and velocity counters
(PRD §3.5, §3.7, §3.8, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_money_order_payload, create_check_cash_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    return_payload,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_return_cascade_recovery_and_risk_tier_bump(api):
    """PRD §3.9: "As a first cascade hop, the customer's `outstanding_recovery_cents` is
    increased by the sum of the check face plus the 2500-cent return fee. As a second
    cascade hop, 250 points are confirmed onto the customer's `risk_score`, which may in
    turn bump the `risk_tier` as described in §3.8."
    PRD §3.8: "it is `STANDARD` while the score is below 350, `ELEVATED` while the score
    is at least 350 and below 700".

    Two CHECK_CASH face=100000 each, both returned: outstanding = 2*(100000+2500) = 205000;
    risk_score = 2*250 = 500 -> tier ELEVATED.

    Design: Difficulty/transitive_cascade/return_cascade_depth3_recovery_then_risk_tier_bump
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="S7", opening_float_cents=2000000)
    txn1 = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    txn2 = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    validate_success(api.return_transaction(txn1["id"], return_payload("NSF"), MANAGER), 201)

    validate_success(api.return_transaction(
        txn2["id"], return_payload("ACCOUNT_CLOSED"), MANAGER), 201)

    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["outstanding_recovery_cents"] == 205000
    assert cust_after["risk_score"] == 500
    assert cust_after["risk_tier"] == "ELEVATED"
    txn2_after = validate_success(api.get_transaction(txn2["id"], TELLER), 200)
    assert txn2_after["settlement_state"] == "RETURNED"


def test_void_cascade_drawer_and_velocity_reversal(api):
    """PRD §3.7: "Voiding moves the transaction to `lifecycle_state` `VOIDED`, sets the
    product child to its voided form ..., recomputes the drawer's expected cash by reversing
    the original net impact, and decrements the customer's `daily_cashed_amount_cents` and
    `daily_transaction_count` as compensation for the original posting."

    MONEY_ORDER face=50000, fee=349 (min(99+250,500)) -> expected 1000000+50349=1050349,
    count 1. After void: expected restored to 1000000, count 0.

    Design: Difficulty/transitive_cascade/void_cascade_depth2_drawer_and_velocity_reversal
    """
    cust, drawer = setup_verified_customer_and_drawer("S8", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Acme"), TELLER), 201)
    drawer_before = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_before["expected_cash_cents"] == 1050349

    validate_success(api.void_transaction(txn["id"], MANAGER), 200)

    drawer_after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_after["expected_cash_cents"] == 1000000
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 0
    txn_after = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert txn_after["lifecycle_state"] == "VOIDED"


def test_void_conserves_drawer_expected_cash(api):
    """PRD §2.9: "A drawer's `expected_cash_cents` is derived, never set directly: it is
    its opening float adjusted by the cash impact of every posted transaction flowing
    through it".
    PRD §3.7: "recomputes the drawer's expected cash by reversing the original net impact".

    Invariant: posting a MONEY_ORDER face=50000 (fee 349) then voiding it must restore
    expected_cash_cents to the exact opening float 1000000.

    Design: Difficulty/compensating_invariant/void_conserves_drawer_expected_cash
    """
    cust, drawer = setup_verified_customer_and_drawer("S17", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Acme"), TELLER), 201)
    drawer_before = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_before["expected_cash_cents"] == 1050349

    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    drawer_after = validate_success(api.get_cash_drawer(drawer["id"], MANAGER), 200)
    assert drawer_after["expected_cash_cents"] == 1000000


def test_void_conserves_customer_velocity_counters(api):
    """PRD §3.7: "decrements the customer's `daily_cashed_amount_cents` and
    `daily_transaction_count` as compensation for the original posting."
    PRD §3.8: "On a successful posting the counters take their projected values, with only
    check-cash face amounts contributing to `daily_cashed_amount_cents`."

    Invariant: a single CHECK_CASH face=100000 -> count 1, cashed 100000; after void BOTH
    counters return to 0.

    Design: Difficulty/compensating_invariant/void_conserves_customer_velocity_counters
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="S18", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    cust_before = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_before["daily_transaction_count"] == 1
    assert cust_before["daily_cashed_amount_cents"] == 100000

    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["daily_transaction_count"] == 0
    assert cust_after["daily_cashed_amount_cents"] == 0
