"""Settlement ledger: provisional commission, final commission delta, refund
reversal, and periodic sweep (PRD §3.8, §3.10).
"""

import pytest

from test_helpers import (
    advance_clock,
    assert_commission_plus_reversal_zero,
    customer_accept,
    drive_order_to,
    expected_final_commission,
    expected_payout_components,
    expected_provisional_commission,
    get_settlement_entries,
    iso_in,
    run_settlement_sweep,
    setup_basic_scenario,
    setup_order_in_state,
    setup_personnel_with_settled_commission_only,
    OPERATOR_HEADERS,
    validate_success,
)


# =============================================================================
# Provisional commission (PRD §3.10)
# =============================================================================


def test_provisional_commission_amount(api):
    """PRD §3.10: "The provisional amount is computed as gross_price_cents
    multiplied by 0.70 and then rounded half-up to integer cents."

    Claim: provisional COMMISSION amount_cents = round_half_up(gross * 0.70).
    """
    ctx = setup_basic_scenario(base_price_cents=10000)
    order = drive_order_to(ctx, "COMPLETED")
    entries = get_settlement_entries(order["assigned_personnel_id"])
    commissions = [
        e
        for e in entries
        if e.get("order_id") == order["id"] and e.get("kind") == "COMMISSION"
    ]
    assert len(commissions) == 1
    assert commissions[0]["amount_cents"] == expected_provisional_commission(
        order["gross_price_cents"]
    )


# =============================================================================
# Final commission delta on customer-accept (PRD §3.10)
# =============================================================================


def test_final_commission_delta_zero_when_tier_unchanged(api):
    """PRD §3.10: "The delta — the final amount minus the provisional amount —
    is posted to the ledger: if the delta is positive it is recorded as a
    BONUS entry, and if it is negative it is recorded as a REVERSAL entry."
    PRD §3.10: "In every case, the invariant provisional + delta == final holds."

    Claim: when tier_at_completion == tier_at_acceptance (BRONZE for a fresh
    personnel), final == provisional and (provisional + sum(delta)) == final.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    entries = get_settlement_entries(order["assigned_personnel_id"])
    related = [e for e in entries if e.get("order_id") == order["id"]]
    commissions = [e for e in related if e["kind"] == "COMMISSION"]
    bonuses = [e for e in related if e["kind"] == "BONUS"]
    reversals = [e for e in related if e["kind"] == "REVERSAL"]
    assert len(commissions) == 1
    provisional = commissions[0]["amount_cents"]
    delta = sum(e["amount_cents"] for e in bonuses) + sum(
        e["amount_cents"] for e in reversals
    )
    # Personnel started BRONZE, no ratings between complete and accept, so the
    # tier did not change. final == provisional → delta == 0.
    final_expected = expected_final_commission(order["gross_price_cents"], "BRONZE")
    assert provisional + delta == final_expected


# =============================================================================
# Refund reversal (PRD §3.8)
# =============================================================================


def test_refund_posts_reversal_summing_to_zero(api):
    """PRD §3.8: "Refund posts a compensating SettlementLedgerEntry with kind
    REVERSAL, whose amount is exactly the negative of the prior COMMISSION
    posting so that the sum of the order's COMMISSION plus REVERSAL ledger
    entries is exactly zero cents after the refund."

    Claim: after refund, sum(COMMISSION+BONUS+REVERSAL for order) == 0 cents.
    """
    ctx, order = setup_order_in_state("COMPLETED")
    api.refund_order(order["id"], OPERATOR_HEADERS)
    entries = get_settlement_entries(order["assigned_personnel_id"])
    assert_commission_plus_reversal_zero(entries, order["id"])


# =============================================================================
# Periodic sweep (PRD §3.10)
# =============================================================================


def test_settlement_sweep_posts_tax_and_payout(api):
    """PRD §3.10: "The sweep posts one TAX entry with the negative tax amount
    and one PAYOUT entry with the negative payout amount, both stamped with
    the supplied cycle_id."

    Claim: after a sweep on a personnel with eligible released commissions,
    exactly one TAX and one PAYOUT entry are written for that cycle.
    """
    setup = setup_personnel_with_settled_commission_only(
        target_amounts_cents=[3333, 3334, 3333], cycle_id="2026-05"
    )
    run_settlement_sweep("2026-05")
    entries = get_settlement_entries(setup["personnel"]["id"], cycle_id="2026-05")
    taxes = [e for e in entries if e["kind"] == "TAX"]
    payouts = [e for e in entries if e["kind"] == "PAYOUT"]
    assert len(taxes) == 1, f"Expected exactly 1 TAX entry, got {taxes}"
    assert len(payouts) == 1, f"Expected exactly 1 PAYOUT entry, got {payouts}"
    # Per PRD §3.10: TAX/PAYOUT entries are negative.
    assert taxes[0]["amount_cents"] < 0
    assert payouts[0]["amount_cents"] < 0


def test_settlement_sweep_sum_then_round_tax(api):
    """PRD §3.10: "the rule is sum-then-round, meaning the sum is computed
    across the eligible entries first and the tax rate is applied to that sum
    once, not entry-by-entry."

    Claim: three commissions of 3333+3334+3333=10000 cents produce TAX=-1000
    (round_half_up(10000*0.10)=1000) NOT TAX=-999 (per-entry 333+333+333).
    """
    setup = setup_personnel_with_settled_commission_only(
        target_amounts_cents=[3333, 3334, 3333], cycle_id="2026-05"
    )
    run_settlement_sweep("2026-05")
    entries = get_settlement_entries(setup["personnel"]["id"], cycle_id="2026-05")
    taxes = [e for e in entries if e["kind"] == "TAX"]
    payouts = [e for e in entries if e["kind"] == "PAYOUT"]
    expected = expected_payout_components([3333, 3334, 3333])
    # tax magnitude is positive; ledger stores negative.
    assert taxes[0]["amount_cents"] == -expected["tax_cents"]
    assert payouts[0]["amount_cents"] == -expected["payout_cents"]
    # Spell out the exact value to anchor the "sum-then-round" rule explicitly.
    assert taxes[0]["amount_cents"] == -1000
    assert payouts[0]["amount_cents"] == -9000


def test_held_back_commission_not_in_sweep(api):
    """PRD §3.10: "An entry is eligible for the current sweep when its kind
    is COMMISSION, BONUS, or REVERSAL and either its withheld_until is null
    or its withheld_until is at or before the current time."

    Claim: a COMMISSION whose withheld_until is in the future (within the 72h
    complaint window) is NOT included in the sweep — no TAX/PAYOUT is posted.
    """
    ctx, order = setup_order_in_state("COMPLETED")
    # Do NOT advance the clock — the commission is still within the 72h hold.
    run_settlement_sweep("2026-06")
    entries = get_settlement_entries(
        order["assigned_personnel_id"], cycle_id="2026-06"
    )
    # Either no TAX/PAYOUT for this cycle, or TAX==0/PAYOUT==0 (payout_base=0).
    taxes = [e for e in entries if e["kind"] == "TAX"]
    payouts = [e for e in entries if e["kind"] == "PAYOUT"]
    # No eligible released entries → the sweep should not have posted positive
    # TAX/PAYOUT. PRD does not commit on whether a no-op cycle posts zero rows
    # or skips entirely, so we assert magnitude only.
    for entry in taxes + payouts:
        assert entry["amount_cents"] == 0, (
            f"Held-back COMMISSION should not contribute to TAX/PAYOUT; got {entry}"
        )
