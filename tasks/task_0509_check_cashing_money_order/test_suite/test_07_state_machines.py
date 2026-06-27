"""Breadth tests on state machines: initial states, valid/invalid transitions,
idempotency, terminal lockdown, preconditions, and cross-entity side effects
(PRD §3.3, §3.5, §3.7, §3.8, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId,
    create_check_cash_payload, create_money_order_payload,
    setup_verified_customer_and_drawer, setup_verified_customer_drawer_and_schedule,
    setup_risk_held_check, setup_returned_check, setup_closed_drawer,
    setup_reconciling_drawer, open_drawer, reconcile_drawer, current_drawer_version,
    get_check_item_for_transaction, return_payload, close_payload,
    make_teller_headers, make_store_manager_headers,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_checkitem_amount_hold_is_risk_held(api):
    """PRD §3.5: "A check is placed on hold — moving `VERIFYING → RISK_HELD` — if any of
    three conditions is met: the face amount is at least 300000 cents".

    Design: Corner/state_machines/checkitem_initial_state_verifying
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="C3", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    assert check["verification_state"] == "RISK_HELD"


def test_maker_high_risk_hold_reason_maker_risk(api):
    """PRD §3.5: "A check is placed on hold ... if any of three conditions is met: the face
    amount is at least 300000 cents ..., or the maker's account risk is `HIGH`, or the
    customer's daily transaction count has already reached 8 within the current window. The
    `hold_reason` is set to the first matching condition evaluated in that exact order:
    `AMOUNT_THRESHOLD` first, then `MAKER_RISK`, then `VELOCITY`."

    face=100000 (< threshold) maker HIGH -> RISK_HELD, hold_reason MAKER_RISK.

    Design: Corner/state_machines/maker_high_risk_hold_reason_maker_risk
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="C4", face_amount_cents=100000, maker_account_risk="HIGH",
        teller_id="teller-1", schedule="govt")
    assert check["verification_state"] == "RISK_HELD"
    assert check["hold_reason"] == "MAKER_RISK"


def test_release_already_cleared_check_invalid_state(api):
    """PRD §3.7: "A held check is resolved only by a `StoreManager`, and only when the
    check item is in `RISK_HELD`."
    PRD §2.11: "then whether the target resource is in a legal state for the requested
    transition (`ERR_INVALID_STATE`)".

    An auto-cleared CHECK_CASH check (face=100000 maker LOW) released -> ERR_INVALID_STATE.

    Design: Corner/state_machines/release_already_cleared_check_invalid_state
    """
    cust, drawer, sched = setup_verified_customer_drawer_and_schedule(
        store_code="C5", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_check_cash_payload(cust["id"], drawer["id"], 100000, sched["id"], "LOW"),
        TELLER), 201)
    check = get_check_item_for_transaction(txn["id"])
    assert check["verification_state"] == "CLEARED"
    res = api.release_check_item(check["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_void_already_voided_transaction_invalid_state(api):
    """PRD §3.7: "A `StoreManager` may **void** a transaction that is in `lifecycle_state`
    `POSTED` ...; an attempt against any other lifecycle state is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/void_already_voided_transaction_invalid_state
    """
    cust, drawer = setup_verified_customer_and_drawer("C6", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "X"), TELLER), 201)
    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    res = api.void_transaction(txn["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_closed_drawer_terminal_lockdown(api):
    """PRD §3.7: "Both `CLOSED` and `OVER_SHORT` are terminal drawer states."
    PRD §3.7: "First, a `StoreManager` begins reconciliation, moving the drawer
    `OPEN → RECONCILING`; this is permitted only when the drawer is `OPEN`".

    begin-reconcile on a CLOSED drawer -> ERR_INVALID_STATE.

    Design: Corner/state_machines/closed_drawer_terminal_lockdown
    """
    drawer = setup_closed_drawer(store_code="C7", opening_float_cents=300000)
    assert drawer["status"] == "CLOSED"
    res = api.begin_reconcile_drawer(drawer["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_drawer_close_over_short_on_variance(api):
    """PRD §3.7: "The drawer's `variance_cents` is set to the counted cash minus the
    expected cash (signed). If the variance is exactly 0 the drawer moves
    `RECONCILING → CLOSED`; if the variance is non-zero it moves `RECONCILING → OVER_SHORT`."

    Expected 500000, counted 499000 -> variance -1000, status OVER_SHORT.

    Design: Corner/state_machines/drawer_close_over_short_on_variance
    """
    drawer, version = setup_reconciling_drawer(store_code="C8", opening_float_cents=500000)
    res = api.close_drawer(drawer["id"], close_payload(499000, version), MANAGER)
    closed = validate_success(res, 200)
    assert closed["status"] == "OVER_SHORT"
    assert closed["variance_cents"] == -1000


def test_write_off_clears_remaining_recovery_and_risk(api):
    """PRD §3.9: "Writing off clears the remaining balance from the customer's
    `outstanding_recovery_cents` (the total owed minus what has been recovered so far) and
    moves the returned item to `WRITTEN_OFF`. A write-off confirms 200 points onto the
    customer's `risk_score`."

    A returned item (risk 250 from the return, outstanding 102500) written off -> status
    WRITTEN_OFF, outstanding 0, risk_score 250+200 = 450.

    Design: Corner/state_machines/write_off_clears_remaining_recovery_and_risk
    """
    cust, drawer, sched, txn, ri = setup_returned_check(
        store_code="C9", face_amount_cents=100000, return_reason="FRAUD",
        teller_id="teller-1")
    res = api.write_off_returned_item(ri["id"], MANAGER)
    written = validate_success(res, 200)
    assert written["status"] == "WRITTEN_OFF"
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["outstanding_recovery_cents"] == 0
    assert cust_after["risk_score"] == 450


def test_begin_reconcile_with_open_risk_held_items_blocked(api):
    """PRD §3.7: "this is permitted only when the drawer is `OPEN` and no transaction on the
    drawer remains in `lifecycle_state` `DRAFT` (that is, no risk-held check is still
    unresolved). If a draft remains, the request is rejected with `ERR_OPEN_ITEMS_REMAIN`."

    Design: Corner/state_machines/begin_reconcile_with_open_risk_held_items_blocked
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="C10", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    assert check["verification_state"] == "RISK_HELD"
    res = api.begin_reconcile_drawer(drawer["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_OPEN_ITEMS_REMAIN, expected_status=409)


def test_return_non_check_cash_invalid_state(api):
    """PRD §3.9: "A return is permitted only on a transaction whose `txn_type` is
    `CHECK_CASH` and which is currently in `lifecycle_state` `POSTED` with `settlement_state`
    `SETTLED`."
    PRD §2.11: "then whether the target resource is in a legal state for the requested
    transition (`ERR_INVALID_STATE`)".

    Returning a MONEY_ORDER -> ERR_INVALID_STATE.

    Design: Corner/state_machines/return_non_check_cash_invalid_state
    """
    cust, drawer = setup_verified_customer_and_drawer("C11", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Y"), TELLER), 201)
    res = api.return_transaction(txn["id"], return_payload("NSF"), MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_money_order_product_child_voided_on_void(api):
    """PRD §3.7: "Voiding moves the transaction to `lifecycle_state` `VOIDED`, sets the
    product child to its voided form (`VOIDED` for a money order or bill payment,
    `RECALLED` for a wire, `REVERSED` for a prepaid load)".

    Design: Corner/state_machines/money_order_product_child_voided_on_void
    """
    cust, drawer = setup_verified_customer_and_drawer("C12", opening_float_cents=1000000)
    txn = validate_success(api.create_transaction(
        create_money_order_payload(cust["id"], drawer["id"], 50000, "Z"), TELLER), 201)
    validate_success(api.void_transaction(txn["id"], MANAGER), 200)
    res = api.list_transaction_money_order(txn["id"], MANAGER)
    data, meta = validate_paginated(res)
    assert len(data) == 1
    assert data[0]["status"] == "VOIDED"
