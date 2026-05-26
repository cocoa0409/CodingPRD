"""Tests covering reimbursement-claim aggregation under both accounting bases
(CASH excludes DISPUTED/REFUNDED; ACCRUAL includes SETTLED+DISPUTED, with
REFUNDED contributing zero because federal_reimbursement_cents was zeroed at
refund). Also covers the compensating-action invariant that a SETTLE+REFUND
pair on a transaction nets to 0 in the CASH claim total.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    setup_two_claims_scenario_setup,
    create_household,
    create_student,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    refund_transaction,
    create_reimbursement_claim,
    submit_reimbursement_claim,
    api_client,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Difficulty rule 1 / instance 2 — CASH vs ACCRUAL aggregation variants.
# ---------------------------------------------------------------------

def test_cash_basis_only_counts_settled_transactions(api):
    """PRD §3.7: "Under `CASH`, only transactions with `status` of `SETTLED`
    are kept; their `federal_reimbursement_cents` values are summed to
    produce `total_reimbursement_cents`."

    Design: Difficulty/dual_variant_calc/reimbursement_variants_cash_vs_accrual
    """
    _hh, _stu, claim, txs = setup_two_claims_scenario_setup(
        school_code="ELEM-101",
        accounting_basis="CASH",
    )
    submitted = submit_reimbursement_claim(claim["id"])
    # Fixture builds 3 SETTLED + 1 REFUNDED. CASH counts only SETTLED,
    # 3 * 470c = 1410. The REFUNDED tx is excluded from CASH per PRD §3.7.
    assert submitted["total_reimbursement_cents"] == 1410, (
        f"CASH sum over 3 SETTLED txs at 470c each = 1410; "
        f"got {submitted['total_reimbursement_cents']}"
    )
    assert submitted["included_transaction_count"] == 3, (
        f"CASH must count exactly 3 transactions; "
        f"got {submitted['included_transaction_count']}"
    )
    assert submitted["status"] == "SUBMITTED"


def test_accrual_basis_includes_settled_and_refunded(api):
    """PRD §3.7: "Under `ACCRUAL`, transactions with `status` of `SETTLED`,
    `DISPUTED`, or `REFUNDED` are kept; their `federal_reimbursement_cents`
    values are summed. ... `REFUNDED` transactions carry zero (because the
    refund has already zeroed their `federal_reimbursement_cents`)".

    Note: PRD's closure rule (also §3.7) blocks claim submission when any
    DISPUTED transaction is in the period, so the DISPUTED branch of the
    ACCRUAL aggregation rule cannot be exercised by a faithful submission
    flow. This test exercises the SETTLED + REFUNDED branches, which the
    PRD likewise lists explicitly.

    Design: Difficulty/dual_variant_calc/reimbursement_variants_cash_vs_accrual
    """
    _hh, _stu, claim, txs = setup_two_claims_scenario_setup(
        school_code="ELEM-101",
        accounting_basis="ACCRUAL",
    )
    submitted = submit_reimbursement_claim(claim["id"])
    # ACCRUAL keeps SETTLED (3 * 470) + REFUNDED (1 * 0 — federal zeroed
    # at refund per §3.6) = 1410. Count = 4 (all kept).
    assert submitted["total_reimbursement_cents"] == 1410, (
        f"ACCRUAL sum = 3*470 SETTLED + 1*0 REFUNDED = 1410; "
        f"got {submitted['total_reimbursement_cents']}"
    )
    assert submitted["included_transaction_count"] == 4, (
        f"ACCRUAL must count all 4 transactions (SETTLED+REFUNDED); "
        f"got {submitted['included_transaction_count']}"
    )


# ---------------------------------------------------------------------
# Difficulty rule 9 / instance 2 — compensating invariant on federal
# reimbursement under CASH-basis claim.
# ---------------------------------------------------------------------

def test_settle_then_refund_pair_contributes_zero_to_cash_claim(api):
    """PRD §3.7: "Under `CASH`, only transactions with `status` of `SETTLED`
    are kept".
    PRD §3.6: "On success the server creates a compensating `LedgerEntry`
    with `entry_type` `MEAL_REFUND`, `amount_cents` equal to the positive
    `paid_charge_cents`, and the same `linked_transaction_id`; reconciles
    `ParentAccount.balance_cents`; zeros the transaction's
    `federal_reimbursement_cents` (the USDA reimbursement is reversed)".

    Design: Difficulty/compensating_invariant/settle_then_refund_zeros_federal_reimbursement_invariant
    """
    set_clock("2026-01-10T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="Lunch", list_price_cents=0,
        federal_reimbursement_free_cents=470,
    )
    # TX_A — stays SETTLED.
    tx_a = create_service_transaction(stu["id"], menu["id"])
    settle_transaction(tx_a["id"])
    # TX_B — SETTLED then REFUNDED.
    tx_b = create_service_transaction(stu["id"], menu["id"])
    tx_b_settled = settle_transaction(tx_b["id"])
    refund_transaction(tx_b_settled["id"], tx_b_settled["version"])

    set_clock("2026-02-01T00:00:00.000Z")
    claim = create_reimbursement_claim(
        "ELEM-101",
        "2026-01-01T00:00:00.000Z",
        "2026-01-31T23:59:59.000Z",
        accounting_basis="CASH",
    )
    submitted = submit_reimbursement_claim(claim["id"])
    # Under CASH, REFUNDED tx_b is excluded entirely; only tx_a contributes.
    assert submitted["total_reimbursement_cents"] == 470, (
        f"only tx_a (470c) counted; tx_b's SETTLE+REFUND pair nets 0 in CASH; "
        f"got {submitted['total_reimbursement_cents']}"
    )
    assert submitted["included_transaction_count"] == 1, (
        f"CASH includes only tx_a; got {submitted['included_transaction_count']}"
    )


def test_refund_zeros_federal_reimbursement_on_transaction_record(api):
    """PRD §3.6: "zeros the transaction's `federal_reimbursement_cents` (the
    USDA reimbursement is reversed)".

    Design: Difficulty/compensating_invariant/settle_then_refund_zeros_federal_reimbursement_invariant
    """
    set_clock("2026-01-10T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="Lunch", list_price_cents=0,
        federal_reimbursement_free_cents=470,
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    assert settled["federal_reimbursement_cents"] == 470, (
        "SETTLE must stamp federal_reimbursement_cents from MenuItem free rate; "
        f"got {settled['federal_reimbursement_cents']}"
    )
    refunded = refund_transaction(settled["id"], settled["version"])
    assert refunded["federal_reimbursement_cents"] == 0, (
        "REFUND must zero federal_reimbursement_cents; "
        f"got {refunded['federal_reimbursement_cents']}"
    )
