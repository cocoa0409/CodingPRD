"""Deposit ledger and damage charges: estimated vs final refund, the
charge -> deposit -> invoice cascade, charge/waive conservation, deposit-overdraw
rejection, and the dispute-then-waive path."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_departed_stay_with_assessed_damage, setup_corporate_stay, assess_damage,
    assert_deposit_conservation_invariant, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


# --- Estimated vs final deposit refund ---

def test_estimated_refund_equals_full_deposit_before_charge(api):
    """PRD §3.8: "Before any damage is charged, the refundable balance equals the
    full `deposit_held_cents` (the estimated refund); once damages resolve, it
    equals `deposit_held_cents` minus `deposit_charged_cents` (the final refund)."

    Design: Difficulty/dual_variant_calc/deposit_estimated_vs_final_refund
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    # Damage is only ASSESSED, not CHARGED, so refundable is still the full deposit.
    assert stay["deposit_refundable_cents"] == 100000


def test_final_refund_nets_charged_damage(api):
    """PRD §3.8: "At any moment, `deposit_charged_cents` equals the sum of
    `amount_cents` across that stay's damage charges whose `status` is `CHARGED`,
    and `deposit_refundable_cents` equals `deposit_held_cents` minus
    `deposit_charged_cents`, floored at zero so it is never negative."

    Design: Difficulty/dual_variant_calc/deposit_estimated_vs_final_refund
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    validate_success(api.charge_damage_charge(ctx["damage"]["id"], PM))
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["deposit_charged_cents"] == 25000
    assert stay["deposit_refundable_cents"] == 75000


# --- Charge cascade: DamageCharge -> Stay ledger -> FINAL invoice ---

def test_charge_updates_stay_deposit_ledger(api):
    """PRD §3.8: "In both charging paths the ledger cascades identically: the stay's
    `deposit_charged_cents` is increased by `amount_cents` and its
    `deposit_refundable_cents` is recomputed; and if the stay's invoice is already
    `FINAL`, the invoice's `damage_total_cents`, `total_settlement_cents`, and
    `deposit_refund_cents` are recomputed to match."

    Design: Difficulty/transitive_cascade/damage_charge_deposit_invoice_cascade
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    charged = validate_success(api.charge_damage_charge(ctx["damage"]["id"], PM))
    assert charged["status"] == "CHARGED"
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["deposit_charged_cents"] == 25000


def test_charge_recomputes_final_invoice_settlement(api):
    """PRD §3.8: "The `total_settlement_cents` is everything the guest owes:
    `amount_due_cents` plus `damage_total_cents`."
    PRD §3.8: "The `damage_total_cents` mirrors the stay's `deposit_charged_cents`
    at settlement."
    PRD §3.8: "The `deposit_refund_cents` is `deposit_held_cents` minus
    `damage_total_cents`, floored at zero."

    Design: Difficulty/transitive_cascade/damage_charge_deposit_invoice_cascade
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    validate_success(api.charge_damage_charge(ctx["damage"]["id"], PM))
    invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], PM))
    assert invoice["damage_total_cents"] == 25000
    assert invoice["total_settlement_cents"] == 667000
    assert invoice["deposit_refund_cents"] == 75000


# --- Conservation across charge then waive-reversal ---

def test_waive_reversal_restores_deposit_ledger(api):
    """PRD §3.8: "A `PropertyManager` waives a `CHARGED` charge, moving it
    `CHARGED` → `WAIVED`. This reverses the earlier debit: the stay's
    `deposit_charged_cents` is decreased by `amount_cents` and
    `deposit_refundable_cents` is recomputed, restoring the conserved deposit"

    Design: Difficulty/compensating_invariant/deposit_conservation_charge_then_waive
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    validate_success(api.charge_damage_charge(ctx["damage"]["id"], PM))
    waived = validate_success(api.waive_damage_charge(ctx["damage"]["id"], PM))
    assert waived["status"] == "WAIVED"
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["deposit_charged_cents"] == 0
    assert stay["deposit_refundable_cents"] == 100000


def test_deposit_conservation_holds_through_charge_and_waive(api):
    """PRD §3.8: "The conservation identity `deposit_held_cents =
    deposit_refundable_cents + deposit_charged_cents` always holds."

    Design: Difficulty/compensating_invariant/deposit_conservation_charge_then_waive
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=100000,
                                                   amount_cents=25000)
    validate_success(api.charge_damage_charge(ctx["damage"]["id"], PM))
    stay_charged = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay_charged["deposit_held_cents"] == 100000
    assert_deposit_conservation_invariant(stay_charged)

    validate_success(api.waive_damage_charge(ctx["damage"]["id"], PM))
    stay_waived = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay_waived["deposit_held_cents"] == 100000
    assert_deposit_conservation_invariant(stay_waived)


# --- Corner: overdraw rejection; dispute-then-waive path ---

def test_charge_exceeding_deposit_rejected(api):
    """PRD §3.8: "This is permitted only if `amount_cents` is at most the stay's
    current `deposit_refundable_cents`, so the charge would not overdraw the
    deposit; a charge that would overdraw is rejected with
    `ERR_DAMAGE_EXCEEDS_DEPOSIT`."

    Design: Corner/calculations/damage_charge_exceeding_deposit_rejected
    """
    ctx = setup_departed_stay_with_assessed_damage(api, deposit_held_cents=50000,
                                                   amount_cents=60000)
    resp = api.charge_damage_charge(ctx["damage"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_DAMAGE_EXCEEDS_DEPOSIT.value)
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["deposit_charged_cents"] == 0


def test_dispute_then_waive_leaves_ledger_untouched(api):
    """PRD §3.8: "A resident `Employee` may dispute an `ASSESSED` charge, moving it
    `ASSESSED` → `DISPUTED`."
    PRD §3.8: "A `PropertyManager` waives a `DISPUTED` charge, moving it `DISPUTED`
    → `WAIVED`. Because a disputed charge was never applied to the ledger, no
    deposit figures change."

    Design: Corner/state_machines/dispute_then_waive_damage_valid_path
    """
    ctx = setup_corporate_stay(api, committed_units=5, deposit_held_cents=100000)
    stay_id = ctx["stay"]["id"]
    validate_success(api.check_in_stay(stay_id, PM))
    validate_success(api.depart_stay(stay_id, {"actual_move_out": "2026-06-30T00:00:00Z"}, PM))
    damage = assess_damage(api, stay_id=stay_id, amount_cents=30000, description="Scuffed floor")
    validate_success(api.dispute_damage_charge(damage["id"], ctx["employee_headers"]))

    waived = validate_success(api.waive_damage_charge(damage["id"], PM))
    assert waived["status"] == "WAIVED"
    stay = validate_success(api.get_stay(stay_id, PM))
    assert stay["deposit_charged_cents"] == 0
    assert stay["deposit_refundable_cents"] == 100000
