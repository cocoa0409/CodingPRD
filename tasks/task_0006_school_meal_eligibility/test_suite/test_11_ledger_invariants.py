"""Tests covering the parent-account ledger invariant: SETTLE + REFUND on a
single transaction nets to zero in `ParentAccount.balance_cents`. Also covers
the side-effect that a refund creates a compensating MEAL_REFUND LedgerEntry.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    setup_approved_application,
    topup_account,
    resolve_parent_account_id,
    get_parent_account,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    refund_transaction,
    api_client,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Difficulty rule 9 / instance 1 — settle then refund leaves balance unchanged.
# ---------------------------------------------------------------------

def test_settle_then_refund_returns_balance_to_pre_settle_value(api):
    """PRD §3.6: "On success the server creates a compensating `LedgerEntry`
    with `entry_type` `MEAL_REFUND`, `amount_cents` equal to the positive
    `paid_charge_cents`, and the same `linked_transaction_id`; reconciles
    `ParentAccount.balance_cents`; zeros the transaction's
    `federal_reimbursement_cents` (the USDA reimbursement is reversed); and
    bumps `version`. The net ledger delta of charge-then-refund on the same
    transaction is zero."

    Design: Difficulty/compensating_invariant/settle_then_refund_leaves_ledger_balance_unchanged
    """
    set_clock("2026-05-01T10:00:00.000Z")
    # PAID-tier household (annual=$80k → PAID).
    hh, stu, approved_app = setup_approved_application(
        clock_iso="2026-05-01T10:00:00.000Z",
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA",
        decision_reason="PAID tier confirmed",
        direct_certification_flag=False,
    )
    pa_id = resolve_parent_account_id(hh["id"])
    topup_account(hh["id"], 5000, idempotency_key="inv-1", parent_account_id=pa_id)
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=300, name="Sandwich",
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    assert settled["paid_charge_cents"] == 300
    balance_after_settle = get_parent_account(hh["id"], pa_id)["balance_cents"]
    assert balance_after_settle == 4700, (
        f"5000 topup - 300 PAID charge = 4700; got {balance_after_settle}"
    )
    refund_transaction(settled["id"], settled["version"])
    balance_after_refund = get_parent_account(hh["id"], pa_id)["balance_cents"]
    assert balance_after_refund == 5000, (
        "after compensating refund, balance returns to pre-settle 5000; "
        f"got {balance_after_refund}"
    )


def test_refund_creates_compensating_meal_refund_ledger_entry(api):
    """PRD §3.6: "On success the server creates a compensating `LedgerEntry`
    with `entry_type` `MEAL_REFUND`, `amount_cents` equal to the positive
    `paid_charge_cents`, and the same `linked_transaction_id`".

    Design: Difficulty/compensating_invariant/settle_then_refund_leaves_ledger_balance_unchanged
    """
    set_clock("2026-05-01T10:00:00.000Z")
    hh, stu, _ = setup_approved_application(
        clock_iso="2026-05-01T10:00:00.000Z",
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA",
        decision_reason="PAID tier",
        direct_certification_flag=False,
    )
    pa_id = resolve_parent_account_id(hh["id"])
    topup_account(hh["id"], 5000, idempotency_key="inv-led-1", parent_account_id=pa_id)
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=300, name="Sandwich",
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    refund_transaction(settled["id"], settled["version"])

    # Read the per-tx ledger.
    res = api.list_ledger_entries(
        TEST_USERS["school_staff_headers"],
        params={"linked_transaction_id": tx["id"]},
    )
    data = validate_success(res, 200)
    rows = data if isinstance(data, list) else data.get("data", data)
    types = sorted(r["entry_type"] for r in rows)
    assert "MEAL_CHARGE" in types and "MEAL_REFUND" in types, (
        f"both MEAL_CHARGE and MEAL_REFUND must exist for tx; got types={types}"
    )
    refund_entry = next(r for r in rows if r["entry_type"] == "MEAL_REFUND")
    assert refund_entry["amount_cents"] == 300, (
        f"MEAL_REFUND amount_cents must equal the positive paid_charge_cents (300); "
        f"got {refund_entry['amount_cents']}"
    )
    assert refund_entry["linked_transaction_id"] == tx["id"]
