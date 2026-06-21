"""Voiding a sale: cascade reversal and the compensation invariants.

Covers the depth-2 void cascade, the cash-payable and store-credit conservation
invariants, and the cross-entity rule that a swept sale can no longer be voided.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    TEST_USERS,
    set_clock, setup_sold_item, setup_finalized_sale,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]


# ─── Difficulty: transitive cascade — sale void depth 2 ──────────────────────

def test_sale_void_returns_item_to_floor(api):
    """PRD §3.7: "For each of the voided sale's lines, the underlying item is
    returned to the floor — its listing dimension moves `SOLD → ON_FLOOR`, its
    frozen `sold_price_cents` is cleared, and its `current_price_cents` is
    recomputed."

    Design: Difficulty/transitive_cascade/sale_void_cascade_reverses_ledger_depth2
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, item, sale = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="void@x.com", consignor_name="Void Vera")
    voided = validate_success(api.void_sale(sale["id"], CASHIER), 200)
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after["listing_status"] == "ON_FLOOR"
    assert after["sold_price_cents"] is None, (
        f"sold_price_cents must be cleared on void, got {after['sold_price_cents']}")


def test_sale_void_reverses_unsettled_payable(api):
    """PRD §3.7: "For lines under a `CASH`-payout agreement, a compensating
    `PayoutLedgerEntry` is appended with an `entry_type` of `REVERSAL` and an
    `amount_cents` equal to the negative of that line's `consignor_proceeds_cents`,
    exactly offsetting the original accrual so the two sum to zero, and the
    consignor's `unsettled_payable_cents` is recomputed."

    Design: Difficulty/transitive_cascade/sale_void_cascade_reverses_ledger_depth2
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, sale = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="void2@x.com", consignor_name="Void Two")
    before = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert before["unsettled_payable_cents"] == 4000
    validate_success(api.void_sale(sale["id"], CASHIER), 200)
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["unsettled_payable_cents"] == 0, (
        f"REVERSAL must zero the payable, got {after['unsettled_payable_cents']}")


# ─── Difficulty: compensating invariant — cash payable conserved ─────────────

def test_void_conserves_cash_payable_balance(api):
    """PRD §3.7: "Voiding cascades the exact inverse of the original sale so the
    consignor's balance returns to its pre-sale value."

    Design: Difficulty/compensating_invariant/sale_void_conserves_consignor_cash_payable
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, sale = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="conserve@x.com", consignor_name="Conserve Cal")
    validate_success(api.void_sale(sale["id"], CASHIER), 200)
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["unsettled_payable_cents"] == 0, (
        f"payable returns to pre-sale 0, got {after['unsettled_payable_cents']}")


def test_void_ledger_entries_sum_to_zero(api):
    """PRD §3.7: "exactly offsetting the original accrual so the two sum to zero".

    Design: Difficulty/compensating_invariant/sale_void_conserves_consignor_cash_payable
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, sale = setup_sold_item(
        split_basis="GROSS", payout_method="CASH", list_price_cents=8000,
        consignor_email="conserve2@x.com", consignor_name="Conserve Two")
    validate_success(api.void_sale(sale["id"], CASHIER), 200)
    entries = validate_success(
        api.list_consignor_ledger_entries(consignor["id"], ADMIN), 200)
    total = sum(e["amount_cents"] for e in entries)
    assert total == 0, f"SALE_PAYOUT + REVERSAL must sum to 0, got {total}"


# ─── Difficulty: compensating invariant — store credit conserved ─────────────

def test_void_conserves_store_credit_balance(api):
    """PRD §3.7: "For lines under a `STORE_CREDIT`-payout agreement, the
    originating `ISSUE` `StoreCreditTransaction` has its `status` flipped to `VOID`
    so it drops out of the posted sum, and the consignor's `store_credit_cents` is
    recomputed."

    Design: Difficulty/compensating_invariant/store_credit_void_conserves_store_credit_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, sale = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=8000,
        consignor_email="creditcon@x.com", consignor_name="Credit Conserve")
    before = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert before["store_credit_cents"] == 4400
    validate_success(api.void_sale(sale["id"], CASHIER), 200)
    after = validate_success(api.get_consignor(consignor["id"], ADMIN), 200)
    assert after["store_credit_cents"] == 0, (
        f"VOID-ing the ISSUE returns credit to 0, got {after['store_credit_cents']}")


def test_void_posted_store_credit_transactions_sum_to_zero(api):
    """PRD §2.7: "A consignor's `store_credit_cents` is the sum of the
    `amount_cents` of all that consignor's `StoreCreditTransaction` records whose
    `status` is `POSTED`; voided transactions are excluded."

    Design: Difficulty/compensating_invariant/store_credit_void_conserves_store_credit_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    consignor, _, _, sale = setup_sold_item(
        split_basis="GROSS", payout_method="STORE_CREDIT", list_price_cents=8000,
        consignor_email="creditcon2@x.com", consignor_name="Credit Conserve Two")
    validate_success(api.void_sale(sale["id"], CASHIER), 200)
    txns = validate_success(
        api.list_consignor_store_credit_transactions(consignor["id"], ADMIN), 200)
    posted_total = sum(t["amount_cents"] for t in txns if t["status"] == "POSTED")
    assert posted_total == 0, f"POSTED store-credit sum must be 0, got {posted_total}"


# ─── Difficulty: cross-entity state dependency — void gated by sweep ─────────

def test_swept_sale_carries_settlement_id(api):
    """PRD §3.9: "The settlement's `id` is stamped as the `settlement_id` onto
    every in-scope `COMPLETED` sale and onto every unsettled `PayoutLedgerEntry`
    whose originating line belongs to those sales."

    Design: Difficulty/cross_entity_state_dependency/sale_void_gated_by_settlement_sweep_state
    """
    _, _, sale, settlement = setup_finalized_sale(
        list_price_cents=8000, business_date="2026-06-05",
        clock_iso="2026-06-05T10:00:00Z", payout_method="CASH",
        consignor_email="swept@x.com", consignor_name="Swept Sue")
    read = validate_success(api.get_sale(sale["id"], SETTLER), 200)
    assert read["settlement_id"] == settlement["id"], (
        f"sale must carry the finalized settlement id, got {read['settlement_id']}")


def test_void_swept_sale_returns_invalid_state(api):
    """PRD §3.7: "A void is only permitted while the sale's `status` is `COMPLETED`
    and its `settlement_id` is still null — a sale already swept into a finalized
    settlement cannot be voided, and the attempt is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/sale_void_gated_by_settlement_sweep_state
    """
    _, _, sale, _ = setup_finalized_sale(
        list_price_cents=8000, business_date="2026-06-05",
        clock_iso="2026-06-05T10:00:00Z", payout_method="CASH",
        consignor_email="swept2@x.com", consignor_name="Swept Two")
    res = api.void_sale(sale["id"], CASHIER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
