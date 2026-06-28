"""Depth tests on the CheckItem branching machine, ReturnedItem recovery cycle,
provisional-vs-confirmed risk scoring, and the recovery equality boundary
(PRD §3.5, §3.7, §3.8, §3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    setup_risk_held_check, setup_partially_recovered_check,
    make_teller_headers, make_store_manager_headers,
    recover_payload,
)

TELLER = make_teller_headers("teller-1")
MANAGER = make_store_manager_headers("manager-9")


def test_risk_score_provisional_not_persisted_then_confirmed_on_release(api):
    """PRD §3.5: "a provisional risk increment is computed and surfaced on the check but
    is **not** written to the customer's confirmed `risk_score` — it remains a what-if
    value that contributes nothing unless and until the hold is resolved."
    PRD §3.8: "When a held check is resolved (released or rejected), the hold-derived
    delta is confirmed: 120 points if the held check's maker account risk was `HIGH`,
    plus 60 points if the hold reason was `AMOUNT_THRESHOLD`, plus 90 points if the hold
    reason was `VELOCITY`."

    A face=350000 (AMOUNT_THRESHOLD) maker LOW hold: before release risk_score==0; after
    release the confirmed delta is +60 (AMOUNT_HOLD_PTS only) -> 60, tier STANDARD.

    Design: Difficulty/dual_variant_calc/customer_risk_score_provisional_vs_confirmed
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="S2", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    before = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert before["risk_score"] == 0, "provisional risk must not be persisted while held"

    released = validate_success(api.release_check_item(check["id"], MANAGER), 200)
    assert released["verification_state"] == "CLEARED"
    after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert after["risk_score"] == 60, f"expected confirmed risk_score 60, got {after['risk_score']}"
    assert after["risk_tier"] == "STANDARD"


def test_checkitem_branch_riskheld_then_reject_voids_txn(api):
    """PRD §3.7: "**Rejecting** a held check moves the check item `RISK_HELD → REJECTED`;
    the parent transaction moves to `lifecycle_state` `VOIDED` while its settlement stays
    `UNSETTLED`, no cash moves, the drawer is untouched, and the same hold-derived risk
    delta is confirmed onto the customer's `risk_score`."
    PRD §3.5: "The `hold_reason` is set to the first matching condition evaluated in that
    exact order: `AMOUNT_THRESHOLD` first, then `MAKER_RISK`, then `VELOCITY`."

    Design: Difficulty/non_linear_state_machine/checkitem_branch_verifying_to_riskheld_then_reject
    """
    cust, drawer, sched, txn, check = setup_risk_held_check(
        store_code="S5", face_amount_cents=350000, maker_account_risk="LOW",
        teller_id="teller-1", schedule="payroll")
    assert check["hold_reason"] == "AMOUNT_THRESHOLD"

    rejected = validate_success(api.reject_check_item(check["id"], MANAGER), 200)
    assert rejected["verification_state"] == "REJECTED"
    fetched = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert fetched["lifecycle_state"] == "VOIDED"
    assert fetched["settlement_state"] == "UNSETTLED"


def test_returned_item_cyclic_partial_recovery_loop(api):
    """PRD §3.9: "If the payment is for less than the remaining balance, the returned item
    moves to `PARTIALLY_RECOVERED` and may receive further partial payments, each repeating
    the same accumulation and customer-balance reduction."

    total_owed = 100000 + 2500 = 102500. First recover 40000 -> PARTIALLY_RECOVERED,
    recovered 40000. Second recover 30000 -> still PARTIALLY_RECOVERED, recovered 70000.
    Settlement remains RETURNED (not yet fully recovered).

    Design: Difficulty/non_linear_state_machine/returned_item_cyclic_partial_recovery_loop
    """
    cust, drawer, sched, txn, ri = setup_partially_recovered_check(
        store_code="S6", face_amount_cents=100000, first_recovery=40000,
        teller_id="teller-1")
    assert ri["status"] == "PARTIALLY_RECOVERED"
    assert ri["recovered_cents"] == 40000

    second = validate_success(api.recover_returned_item(
        ri["id"], recover_payload(30000), TELLER), 200)
    assert second["status"] == "PARTIALLY_RECOVERED"
    assert second["recovered_cents"] == 70000

    fetched_txn = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert fetched_txn["settlement_state"] == "RETURNED"


def test_recovery_exact_balance_equality_recovers(api):
    """PRD §3.9: "If the payment brings `recovered_cents` to exactly the total owed, the
    returned item moves to `RECOVERED` (whether arriving from `OUTSTANDING` directly or
    from `PARTIALLY_RECOVERED`), and the linked transaction's `settlement_state` moves to
    `RECOVERED`."

    total_owed 102500, 40000 already recovered -> remaining 62500. A payment of exactly
    62500 fully satisfies: status RECOVERED, recovered_cents 102500, txn settlement
    RECOVERED, customer outstanding 0.

    Design: Difficulty/boundary_precision_check/recovery_exact_balance_equality_boundary
    """
    cust, drawer, sched, txn, ri = setup_partially_recovered_check(
        store_code="S12", face_amount_cents=100000, first_recovery=40000,
        teller_id="teller-1")
    assert ri["recovered_cents"] == 40000

    final = validate_success(api.recover_returned_item(
        ri["id"], recover_payload(62500), TELLER), 200)
    assert final["status"] == "RECOVERED"
    assert final["recovered_cents"] == 102500

    fetched_txn = validate_success(api.get_transaction(txn["id"], TELLER), 200)
    assert fetched_txn["settlement_state"] == "RECOVERED"
    cust_after = validate_success(api.get_customer(cust["id"], TELLER), 200)
    assert cust_after["outstanding_recovery_cents"] == 0
