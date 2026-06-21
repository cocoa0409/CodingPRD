"""Compensating-action invariants and derived-field reconciliation.

Translates queue A (Difficulty) compensating_invariant and queue B (Corner)
cross_cutting_complexity_layers / derived_field_reconciliation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_fee_schedule, create_seller, create_order,
    onboard_active_seller, schedule_payout, current_seller_version,
    seller_with_scheduled_payout,
    set_clock, advance_clock, create_chargeback,
    make_seller_headers, make_finance_headers,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / payout_release_then_reverse_leaves_balance_unchanged
# ─────────────────────────────────────────────────────────────────────────────

def test_payout_release_then_reverse_restores_available_balance(api, finance_headers):
    """PRD §3.9: "A `RELEASED` payout whose disbursement is later clawed back by the
    bank can be reversed: the platform posts a positive `PAYOUT` reversal ledger
    entry restoring the available balance, flips the swept orders' `settlement_status`
    from `PAID` back to `AVAILABLE` as a compensating cascade ... and reconciles
    balances such that the net effect on `available_balance_cents` is zero."

    Design: Difficulty/compensating_invariant/payout_release_then_reverse_leaves_available_balance_unchanged
    """
    # STANDARD seller, +8130 AVAILABLE, payout released then reversed.
    seller, order, payout, _pm = seller_with_scheduled_payout(
        gross_amount_cents=10000, settle_iso="2026-03-01T00:00:00Z",
        mature_iso="2026-03-10T00:00:00Z",
    )
    before_release = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert before_release["available_balance_cents"] == 8130

    version = current_seller_version(seller["id"])
    released = validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    reversed_payout = validate_success(
        api.reverse_payout(payout["id"], make_finance_headers("finance-2")), 200
    )
    assert reversed_payout["payout_status"] == "REVERSED"
    after_reverse = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert after_reverse["available_balance_cents"] == 8130
    restored_order = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert restored_order["settlement_status"] == "AVAILABLE"


def test_payout_reverse_flips_orders_back_to_available(api, finance_headers):
    """PRD §3.9: "flips the swept orders' `settlement_status` from `PAID` back to
    `AVAILABLE` as a compensating cascade".

    Design: Difficulty/compensating_invariant/payout_release_then_reverse_leaves_available_balance_unchanged
    """
    seller, order, payout, _pm = seller_with_scheduled_payout(
        gross_amount_cents=10000, settle_iso="2026-03-01T00:00:00Z",
        mature_iso="2026-03-10T00:00:00Z",
    )
    version = current_seller_version(seller["id"])
    validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    paid = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert paid["settlement_status"] == "PAID"
    validate_success(api.reverse_payout(payout["id"], make_finance_headers("finance-2")), 200)
    restored = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert restored["settlement_status"] == "AVAILABLE"


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / chargeback_won_restores_clawback_but_keeps_dispute_fee
# ─────────────────────────────────────────────────────────────────────────────

def test_chargeback_won_keeps_dispute_fee_conserves_gross(api, finance_headers):
    """PRD §3.7: "From `REPRESENTED`, an `outcome` in the seller's favour moves it to
    `WON`: any previously posted full-gross clawback is reversed, but the
    `dispute_fee_cents` is not refunded."
    PRD §3.7: "the fee is never recovered even if a later representment had won."

    Design: Difficulty/compensating_invariant/chargeback_won_restores_clawback_but_keeps_dispute_fee_conserved_gross
    """
    # Order gross 20000 matured AVAILABLE (proceeds +16340); chargeback RECEIVED
    # (fee -1500), REPRESENTED, then WON. Available = 16340 - 1500 = 14840.
    set_clock("2026-04-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=20000)
    advance_clock("2026-04-10T00:00:00Z")  # matures: net 16340 AVAILABLE
    cb = create_chargeback(order["id"])
    validate_success(api.represent_chargeback(cb["id"], make_seller_headers(seller["id"])), 200)
    decided = validate_success(
        api.decide_chargeback(cb["id"], {"outcome": "WON"}, make_finance_headers("finance-2")), 200
    )
    assert decided["chargeback_status"] == "WON"
    assert decided["dispute_fee_cents"] == 1500
    refetched_seller = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    # Gross conserved; only the 1500 fee is a permanent loss: 16340 - 1500 = 14840.
    assert refetched_seller["available_balance_cents"] == 14840


def test_chargeback_received_levies_flat_fee_on_balance(api, finance_headers):
    """PRD §3.7: "it ... immediately levies a flat, non-refundable fee. That
    `dispute_fee_cents` is fixed at fifteen hundred cents and is posted at once as a
    negative `CHARGEBACK_FEE` ledger entry, after which the seller's balances and
    risk score are reconciled".

    Design: Difficulty/compensating_invariant/chargeback_won_restores_clawback_but_keeps_dispute_fee_conserved_gross
    """
    set_clock("2026-04-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=20000)
    advance_clock("2026-04-10T00:00:00Z")  # matures: net 16340 AVAILABLE
    before = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert before["available_balance_cents"] == 16340
    cb = create_chargeback(order["id"])
    assert cb["dispute_fee_cents"] == 1500
    after = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    # The -1500 CHARGEBACK_FEE entry posts in AVAILABLE: 16340 - 1500 = 14840.
    assert after["available_balance_cents"] == 14840


# ─────────────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers — derived_field_reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def test_reserve_held_reconciled_after_elevated_tier_release(api, finance_headers):
    """PRD §3.9: "posts a negative `RESERVE_HOLD` ledger entry for the withheld
    reserve and opens or extends the reserve".
    PRD §2.6: "The `reserve_held_cents` mirrors the seller's currently open reserve."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reserve_held_reconciled_after_release
    """
    # ELEVATED tier: 2 orders, 1 chargeback RECEIVED → cb_rate 0.5 → score 30 → ELEVATED (20%).
    # Order1 gross 10000 matured (+8130); Order2 gross 5000 with chargeback RECEIVED
    # (fee -1500). Available 8130 - 1500 = 6630. Reserve round(6630*20/100)=1326.
    set_clock("2026-11-01T00:00:00Z")
    seller, _pm = onboard_active_seller()
    sid = seller["id"]
    order1 = create_order(sid, gross_amount_cents=10000)
    advance_clock("2026-11-10T00:00:00Z")  # order1 matures (+8130)
    order2 = create_order(sid, gross_amount_cents=5000)
    create_chargeback(order2["id"])  # fee -1500; cb_rate 1/2=0.5 → score 30 → ELEVATED
    payout = schedule_payout(sid)
    version = current_seller_version(sid)
    released = validate_success(
        api.release_payout(payout["id"], {"expected_seller_version": version},
                           make_finance_headers("finance-2")),
        200,
    )
    assert released["reserve_withheld_cents"] == 1326
    assert released["payout_amount_cents"] == 5304
    refetched_seller = validate_success(api.get_seller(sid, finance_headers), 200)
    assert refetched_seller["reserve_held_cents"] == 1326
