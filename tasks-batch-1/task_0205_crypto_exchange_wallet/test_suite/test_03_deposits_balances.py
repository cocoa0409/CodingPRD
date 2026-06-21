"""Deposits, the network-confirmation hold, cost-basis lot seeding, and balances."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, assert_deposit, assert_cost_basis_lot,
    assert_balance, find_balance, ApiErrorId,
    set_clock, create_usd_asset, create_btc_asset, create_account, create_account_at_tier,
    credit_fiat, find_lot_by_unit_cost,
)

OP = TEST_USERS["operator_headers"]


# ===========================================================================
# Corner / entities — balance listing envelope
# ===========================================================================
def test_balance_listing_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."
    PRD §3.4: "A fiat asset short-circuits the hold: a confirmation advance on a
    `DETECTED` fiat deposit moves it directly along `DETECTED → CREDITED`, crediting
    `available_amount` immediately"

    Design: Corner/entities/balance_listing_pagination_envelope
    """
    create_usd_asset()
    acc = create_account(email="bal@x.com", full_name="Bal")
    acc_id = acc["id"]
    credit_fiat(acc_id, "USD", 100)
    trader = make_trader_headers(acc_id)
    data, meta = validate_paginated(api.list_balances(trader, params={"account_id": acc_id}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    usd = find_balance(data, "USD")
    assert usd["available_amount"] == 100


# ===========================================================================
# Corner / calculations — deposit seeds a cost-basis lot
# ===========================================================================
def test_deposit_creates_lot_with_correct_unit_cost(api):
    """PRD §3.4: "a cost-basis lot is opened for the credited funds — with
    `origin_type` of `DEPOSIT`, `origin_id` set to the deposit's `id`,
    `original_quantity` and `remaining_quantity` both equal to the deposited amount,
    `unit_cost_usd` copied from the deposit, and `acquired_at` set to the current
    clock."

    Design: Corner/calculations/deposit_creates_lot_with_correct_unit_cost
    """
    create_btc_asset(required_confirmations=2)
    acc = create_account(email="dl@x.com", full_name="DL")
    acc_id = acc["id"]
    dep = validate_success(api.create_deposit(
        {"account_id": acc_id, "asset": "BTC", "amount": 2.0, "unit_cost_usd": 35000},
        OP), 201)
    # Non-fiat deposits pass through CONFIRMING (PRD §3.4): first advance enters
    # CONFIRMING (held), a subsequent advance reaching required credits the lot.
    validate_success(api.advance_confirmations(dep["id"], {"delta": 1}, OP))
    validate_success(api.advance_confirmations(dep["id"], {"delta": 2}, OP))
    trader = make_trader_headers(acc_id)
    lots, _ = validate_paginated(api.list_cost_basis_lots(
        trader, params={"account_id": acc_id, "asset": "BTC"}))
    assert len(lots) == 1
    lot = lots[0]
    assert lot["origin_type"] == "DEPOSIT"
    assert lot["status"] == "OPEN"
    assert lot["original_quantity"] == 2.0
    assert lot["remaining_quantity"] == 2.0
    assert lot["unit_cost_usd"] == 35000
    assert_cost_basis_lot(lot)


# ===========================================================================
# Corner / state_machines — orphan on a CREDITED deposit is invalid
# ===========================================================================
def test_deposit_orphan_from_credited_returns_invalid_state(api):
    """PRD §3.4: "An `Operator` may instead mark a still-`DETECTED` deposit as
    orphaned, moving it along `DETECTED → ORPHANED` with no balance change because
    nothing was credited."

    Design: Corner/state_machines/deposit_orphan_from_credited_returns_invalid_state
    """
    create_usd_asset()
    acc = create_account(email="do@x.com", full_name="DO")
    acc_id = acc["id"]
    dep = validate_success(api.create_deposit(
        {"account_id": acc_id, "asset": "USD", "amount": 50, "unit_cost_usd": 1},
        OP), 201)
    validate_success(api.advance_confirmations(dep["id"], {"delta": 0}, OP))
    resp = api.orphan_deposit(dep["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Difficulty / boundary_precision_check — confirmations exact-required edge
# Two tests: (1) the X (=2, below required) stays CONFIRMING/held;
#            (2) reaching exactly required (3) credits available.
# ===========================================================================
def test_deposit_below_required_confirmations_stays_held(api):
    """PRD §3.4: "A subsequent advance that still leaves the running count below the
    asset's `required_confirmations` keeps the deposit `CONFIRMING → CONFIRMING`,
    incrementing `confirmations` only."
    PRD §3.4: "the first advance from `DETECTED` moves the deposit along
    `DETECTED → CONFIRMING`: it increments `confirmations` by the `delta` and credits
    the deposit's `amount` into the balance's `held_amount`, so the funds are visible
    but not yet spendable."

    Design: Difficulty/boundary_precision_check/deposit_confirmations_exact_required_credits
    """
    set_clock("2026-11-10T00:00:00Z")
    create_btc_asset(required_confirmations=3)
    acc = create_account(email="cf1@x.com", full_name="CF1")
    acc_id = acc["id"]
    dep = validate_success(api.create_deposit(
        {"account_id": acc_id, "asset": "BTC", "amount": 0.5, "unit_cost_usd": 39000},
        OP), 201)
    validate_success(api.advance_confirmations(dep["id"], {"delta": 2}, OP))
    fetched = validate_success(api.get_deposit(dep["id"], OP))
    assert fetched["status"] == "CONFIRMING"
    bals, _ = validate_paginated(api.list_balances(OP, params={"account_id": acc_id, "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    assert btc["available_amount"] == 0
    assert btc["held_amount"] == 0.5


def test_deposit_reaching_exact_required_credits_available(api):
    """PRD §3.4: "An advance that brings the count to at least
    `required_confirmations` moves the deposit along `CONFIRMING → CREDITED`:
    `confirmations` is set to its new total, the deposit's `amount` is moved from
    `held_amount` into `available_amount`"

    Design: Difficulty/boundary_precision_check/deposit_confirmations_exact_required_credits
    """
    set_clock("2026-11-10T00:00:00Z")
    create_btc_asset(required_confirmations=3)
    acc = create_account(email="cf2@x.com", full_name="CF2")
    acc_id = acc["id"]
    dep = validate_success(api.create_deposit(
        {"account_id": acc_id, "asset": "BTC", "amount": 0.5, "unit_cost_usd": 39000},
        OP), 201)
    validate_success(api.advance_confirmations(dep["id"], {"delta": 2}, OP))
    # one more confirmation reaches exactly 3 (== required)
    validate_success(api.advance_confirmations(dep["id"], {"delta": 1}, OP))
    fetched = validate_success(api.get_deposit(dep["id"], OP))
    assert fetched["status"] == "CREDITED"
    bals, _ = validate_paginated(api.list_balances(OP, params={"account_id": acc_id, "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    assert btc["available_amount"] == 0.5
    assert btc["held_amount"] == 0
