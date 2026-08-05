"""Supervision-fee variants, per-line rounding order, and ledger conservation.

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml rules dual_variant_calc.supervision_fee_*,
combinatorial_formula.supervision_fee_round_per_line_then_sum, and
compensating_invariant.ledger_charge_reversal_conserves_balance.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    create_defendant, create_fee_payload, create_ledger_entry_payload,
)

INTAKE = TEST_USERS["intake_headers"]
SUPERVISING = TEST_USERS["supervising_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── dual_variant_calc / supervision_fee_assessed_vs_adjusted ──────────────

def test_assessed_fee_charges_all_three_lines(api):
    """PRD §3.8: "For a non-indigent defendant (the `ASSESSED` variant), the charged amount
    is the sum of all three rounded lines — supervision, EM, and testing."

    Design: Difficulty/dual_variant_calc/supervision_fee_assessed_vs_adjusted
    """
    d = create_defendant(indigent=False)
    entry = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    assert entry["amount_cents"] == 22576, f"ASSESSED total, got {entry['amount_cents']}"
    assert entry["entry_type"] == "CHARGE"

    fresh = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert fresh["balance_owed_cents"] == 22576


def test_adjusted_fee_waives_supervision_and_em_lines(api):
    """PRD §3.8: "For an indigent defendant (the `ADJUSTED` variant), the supervision and EM
    lines are waived entirely and only the rounded testing line is charged."

    Design: Difficulty/dual_variant_calc/supervision_fee_assessed_vs_adjusted
    """
    d = create_defendant(indigent=True)
    entry = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    assert entry["amount_cents"] == 10750, f"ADJUSTED testing line only, got {entry['amount_cents']}"

    fresh = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert fresh["balance_owed_cents"] == 10750


# ─── combinatorial_formula / supervision_fee_round_per_line_then_sum ───────

def test_assessed_fee_rounds_each_line_before_summing(api):
    """PRD §3.8: "Because each line is rounded before summing, the `ASSESSED` total can
    differ by a cent from a sum-then-round computation; the per-line-first order is the
    pinned, required behavior."

    Design: Difficulty/combinatorial_formula/supervision_fee_round_per_line_then_sum
    """
    d = create_defendant(indigent=False)
    entry = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    assert entry["amount_cents"] == 22576, \
        "per-line rounding then sum == 4838+6988+10750 == 22576"


def test_assessed_fee_not_equal_sum_then_round(api):
    """PRD §2.6: "the pinned order is to round each line **first** and only then sum the
    rounded lines; the system never sums the raw un-rounded lines and rounds once at the end."

    Design: Difficulty/combinatorial_formula/supervision_fee_round_per_line_then_sum
    """
    d = create_defendant(indigent=False)
    entry = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    assert entry["amount_cents"] != 22575, \
        "a sum-then-round order would yield 22575; per-line-first is required"


# ─── compensating_invariant / ledger_charge_reversal_conserves_balance ─────

def test_charge_then_reversal_nets_balance_to_zero(api):
    """PRD §2.6: "a `REVERSAL` contributes exactly the negation of the entry it reverses.
    Consequently a charge and its reversal net to zero."

    Design: Difficulty/compensating_invariant/ledger_charge_reversal_conserves_balance
    """
    d = create_defendant(indigent=False)
    charge = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    assert charge["amount_cents"] == 22576

    reversal = validate_success(api.create_ledger_entry(
        d["id"], create_ledger_entry_payload("REVERSAL", reverses_entry_id=charge["id"]),
        ADMIN), 201)
    assert reversal["amount_cents"] == -22576, "REVERSAL negates the referenced amount"

    fresh = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert fresh["balance_owed_cents"] == 0


def test_balance_equals_signed_sum_of_ledger_entries(api):
    """PRD §2.6: "A defendant's `balance_owed_cents` ... always equals the signed sum of
    that defendant's `LedgerEntry.amount_cents`. A `CHARGE` contributes a positive amount."

    Design: Difficulty/compensating_invariant/ledger_charge_reversal_conserves_balance
    """
    d = create_defendant(indigent=False)
    charge = validate_success(api.create_fee(
        d["id"], create_fee_payload(supervision_days=15, em_days=10, scheduled_test_count=4),
        SUPERVISING), 201)
    mid = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert mid["balance_owed_cents"] == charge["amount_cents"] == 22576

    validate_success(api.create_ledger_entry(
        d["id"], create_ledger_entry_payload("REVERSAL", reverses_entry_id=charge["id"]),
        ADMIN), 201)
    final = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert final["balance_owed_cents"] == 22576 - 22576 == 0
