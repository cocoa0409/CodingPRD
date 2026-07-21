"""Trade-in valuation, the dispute cycle, settlement, and void reversal.

Difficulty: dual_variant_calc, non_linear_state_machine (cycle), transitive_cascade
(void reversal), compensating_invariant (store-credit conservation). Corner:
calculations, state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_trade_in, TEST_USERS,
    setup_submitted_tradein, setup_offered_tradein, setup_settled_tradein,
    grade_payload,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: trade_in provisional vs final diverges ───────────────────
def test_tradein_provisional_value_from_stated_grade(api):
    """PRD §3.6: "The provisional valuation uses the member's stated_grade and writes
    provisional_value_cents at intake."
    PRD §3.6: "if the payout_method is STORE_CREDIT, the value is the graded amount
    increased by a ten percent store-credit bonus (the graded amount multiplied by 1.10),
    again rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_diverges_on_regrade
    """
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents=10000, stated_grade="B", payout_method="STORE_CREDIT")
    assert_trade_in(trade_in)
    assert trade_in["provisional_value_cents"] == 8250
    assert trade_in["status"] == "SUBMITTED"


def test_tradein_final_value_diverges_from_provisional_on_regrade(api):
    """PRD §3.6: "The final valuation uses the clerk's final_grade and writes
    final_value_cents; it diverges from the provisional value whenever the clerk's
    final_grade differs from the member's stated_grade."
    PRD §3.6: "Grading a SUBMITTED trade-in advances it SUBMITTED → OFFERED, sets
    final_grade, and pins final_value_cents from the final valuation."

    Design: Difficulty/dual_variant_calc/trade_in_provisional_vs_final_diverges_on_regrade
    """
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents=10000, stated_grade="B", payout_method="STORE_CREDIT")
    graded = validate_success(api.grade_trade_in(trade_in["id"], grade_payload("C"), CLERK), 200)
    assert graded["final_value_cents"] == 5500
    assert graded["provisional_value_cents"] == 8250
    assert graded["final_value_cents"] != graded["provisional_value_cents"]
    assert graded["status"] == "OFFERED"


# ─── Difficulty: offered/disputed/regrade cycle ───────────────────────────
def test_tradein_dispute_regrade_cycle_returns_to_offered(api):
    """PRD §3.6: "If the member is unhappy, they may dispute the current offer, moving it
    OFFERED → DISPUTED, which sends it back for re-grading with no value change. The clerk
    then re-grades a DISPUTED trade-in, moving it DISPUTED → OFFERED, overwriting
    final_grade and recomputing final_value_cents."

    Design: Difficulty/non_linear_state_machine/tradein_offered_disputed_regrade_cycle
    """
    member, product, trade_in = setup_offered_tradein(
        base_trade_value_cents=10000, stated_grade="D", final_grade="C",
        payout_method="STORE_CREDIT")
    disputed = validate_success(api.dispute_trade_in(trade_in["id"], CLERK), 200)
    assert disputed["status"] == "DISPUTED"

    regraded = validate_success(api.grade_trade_in(trade_in["id"], grade_payload("B"), CLERK), 200)
    assert regraded["status"] == "OFFERED"
    assert regraded["final_grade"] == "B"


def test_tradein_regrade_recomputes_final_value(api):
    """PRD §3.6: "The clerk then re-grades a DISPUTED trade-in, moving it DISPUTED →
    OFFERED, overwriting final_grade and recomputing final_value_cents."

    Design: Difficulty/non_linear_state_machine/tradein_offered_disputed_regrade_cycle
    """
    member, product, trade_in = setup_offered_tradein(
        base_trade_value_cents=10000, stated_grade="D", final_grade="C",
        payout_method="STORE_CREDIT")
    api.dispute_trade_in(trade_in["id"], CLERK)
    regraded = validate_success(api.grade_trade_in(trade_in["id"], grade_payload("B"), CLERK), 200)
    assert regraded["final_value_cents"] == 8250


# ─── Difficulty: void settled trade-in reverses store credit ──────────────
def test_void_settled_tradein_zeroes_balance(api):
    """PRD §3.6: "If the settlement had created a TRADE_IN_PAYOUT entry (that is, it was a
    store-credit payout), the void is a compensating action: hop 1 appends a
    StoreCreditEntry with reason TRADE_IN_VOID_REVERSAL and an amount_cents equal to the
    negative of final_value_cents, and hop 2 recomputes the member's
    store_credit_balance_cents from the ledger, returning the balance to its
    pre-settlement value."

    Design: Difficulty/transitive_cascade/void_settled_tradein_reverses_store_credit
    """
    member, product, trade_in = setup_settled_tradein(
        base_trade_value_cents=10000, stated_grade="A", final_grade="A",
        payout_method="STORE_CREDIT")
    assert trade_in["final_value_cents"] == 11000

    voided = validate_success(api.void_trade_in(trade_in["id"], MANAGER), 200)
    assert voided["status"] == "VOIDED"
    fetched = validate_success(api.get_member(member["id"], CLERK), 200)
    assert fetched["store_credit_balance_cents"] == 0


def test_void_settled_tradein_appends_reversal_entry(api):
    """PRD §3.6: "hop 1 appends a StoreCreditEntry with reason TRADE_IN_VOID_REVERSAL and
    an amount_cents equal to the negative of final_value_cents."

    Design: Difficulty/transitive_cascade/void_settled_tradein_reverses_store_credit
    """
    member, product, trade_in = setup_settled_tradein(
        base_trade_value_cents=10000, stated_grade="A", final_grade="A",
        payout_method="STORE_CREDIT")
    api.void_trade_in(trade_in["id"], MANAGER)

    data, meta = validate_paginated(api.list_member_store_credit_entries(member["id"], CLERK))
    reversals = [e for e in data if e["reason"] == "TRADE_IN_VOID_REVERSAL"]
    assert any(e["amount_cents"] == -11000 for e in reversals)


# ─── Difficulty: store-credit conservation across accept then void ────────
def test_store_credit_returns_to_presettlement_value(api):
    """PRD §3.6: "returning the balance to its pre-settlement value."
    PRD §2.8: "The balance invariant holds after every mutation, including compensating
    reversals: store_credit_balance_cents equals the sum of the amount_cents of all of
    that member's entries, and it is never negative."

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_tradein_accept_then_void
    """
    member, product, trade_in = setup_settled_tradein(
        base_trade_value_cents=10000, stated_grade="A", final_grade="A",
        payout_method="STORE_CREDIT")
    api.void_trade_in(trade_in["id"], MANAGER)
    fetched = validate_success(api.get_member(member["id"], CLERK), 200)
    assert fetched["store_credit_balance_cents"] == 0


def test_store_credit_credited_on_accept_then_removed_on_void(api):
    """PRD §3.6: "If the payout_method is STORE_CREDIT, settlement appends a
    StoreCreditEntry with reason TRADE_IN_PAYOUT and an amount_cents equal to the positive
    final_value_cents, and the member's store_credit_balance_cents is recomputed."

    Design: Difficulty/compensating_invariant/store_credit_conserved_across_tradein_accept_then_void
    """
    member, product, trade_in = setup_settled_tradein(
        base_trade_value_cents=10000, stated_grade="A", final_grade="A",
        payout_method="STORE_CREDIT")
    after_accept = validate_success(api.get_member(member["id"], CLERK), 200)
    assert after_accept["store_credit_balance_cents"] == 11000

    api.void_trade_in(trade_in["id"], MANAGER)
    after_void = validate_success(api.get_member(member["id"], CLERK), 200)
    assert after_void["store_credit_balance_cents"] == 0


# ─── Corner: calculations / cash payout has no bonus ──────────────────────
def test_cash_payout_has_no_store_credit_bonus(api):
    """PRD §3.6: "if the payout_method is CASH, the value is simply the graded amount with
    no bonus."

    Design: Corner/calculations/trade_in_cash_payout_has_no_store_credit_bonus
    """
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents=10000, stated_grade="A", payout_method="CASH")
    assert trade_in["provisional_value_cents"] == 10000
    graded = validate_success(api.grade_trade_in(trade_in["id"], grade_payload("A"), CLERK), 200)
    assert graded["final_value_cents"] == 10000


# ─── Corner: state_machines / grading a settled trade-in ──────────────────
def test_grade_settled_tradein_rejected(api):
    """PRD §3.6: "Every lifecycle action above requires the trade-in to be in the correct
    originating state — grading a non-SUBMITTED/non-DISPUTED trade-in, disputing a
    non-OFFERED one, accepting a non-OFFERED one, or voiding a non-SETTLED one is rejected
    with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/grade_settled_tradein_rejected
    """
    member, product, trade_in = setup_settled_tradein(
        base_trade_value_cents=4000, stated_grade="A", final_grade="A",
        payout_method="CASH")
    res = api.grade_trade_in(trade_in["id"], grade_payload("B"), CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: state_machines / disputing a non-offered trade-in ────────────
def test_dispute_non_offered_tradein_rejected(api):
    """PRD §3.6: "Every lifecycle action above requires the trade-in to be in the correct
    originating state — grading a non-SUBMITTED/non-DISPUTED trade-in, disputing a
    non-OFFERED one, accepting a non-OFFERED one, or voiding a non-SETTLED one is rejected
    with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/dispute_non_offered_tradein_rejected
    """
    member, product, trade_in = setup_submitted_tradein(
        base_trade_value_cents=4000, stated_grade="B", payout_method="CASH")
    assert trade_in["status"] == "SUBMITTED"
    res = api.dispute_trade_in(trade_in["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
