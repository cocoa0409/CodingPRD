"""Finalize forks: sealing vs condemnation, penalties, cascades to balance.

Covers difficulty instances price_penalty_per_item_rounding_mode_b,
device_seal_condemn_reseal_cycle, inspection_finalize_pass_fail_branch,
fail_condemn_penalty_balance_depth3; plus corner penalty-multiplier and
seals-reverse-lookup instances.
"""
from test_helpers import (
    bootstrap_est_inspector, register_device,
    accuracy_pass_seal, accuracy_fail_condemn, in_progress_accuracy,
    in_progress_price, schedule_inspection, start_inspection, add_reading,
    finalize_inspection, get_device, get_establishment,
    first_penalty_for_device, penalties_for_device,
    first_condemnation_for_device, first_seal_for_device, seals_for_device,
)


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/price_penalty_per_item_rounding_mode_b
# --------------------------------------------------------------------------- #
_PRICE_ITEMS = [("SKU1", 100, 133), ("SKU2", 200, 247), ("SKU3", 500, 520)]  # overcharges 33,47,20


def test_price_verification_three_mispriced_items_fails():
    """PRD §3.6: "The inspection's computed outcome is `FAIL` when the number of
    mispriced items is strictly greater than 2, and `PASS` otherwise (so exactly two
    mispriced items still passes)."

    Design: Difficulty/combinatorial_formula/price_penalty_per_item_rounding_mode_b
    """
    est, inspector = bootstrap_est_inspector(est_name="Scan Store", jurisdiction="CA-04")
    dev = register_device(est["id"], device_type="SCANNER", serial_number="SN-SC")
    ins = in_progress_price(inspector, dev, "2026-03-06T09:00:00Z",
                            "2026-03-06T10:00:00Z", _PRICE_ITEMS)
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["outcome"] == "FAIL", "3 mispriced items > 2 must FAIL"


def test_price_penalty_uses_per_item_then_sum_rounding():
    """PRD §3.7: "For each such item, multiply its `overcharge_cents` by the penalty
    rate of 1.5 and round that product half up to whole cents. Sum these per-item
    rounded amounts to form a subtotal, then multiply the subtotal by the repeat-offense
    multiplier and round half up to whole cents. This order is authoritative and must
    not be rearranged: round each item first, then sum, then apply the multiplier, then
    round the final figure."
    PRD §3.7: "a failing price verification records `PRICE_ERROR`".

    Design: Difficulty/combinatorial_formula/price_penalty_per_item_rounding_mode_b
    """
    est, inspector = bootstrap_est_inspector(est_name="Scan Store", jurisdiction="CA-04")
    dev = register_device(est["id"], device_type="SCANNER", serial_number="SN-SC")
    ins = in_progress_price(inspector, dev, "2026-03-06T09:00:00Z",
                            "2026-03-06T10:00:00Z", _PRICE_ITEMS)
    finalize_inspection(ins["id"], inspector["id"])
    penalty = first_penalty_for_device(dev["id"])
    # round(49.5)+round(70.5)+round(30) = 50+71+30 = 151 (sum-then-round would give 150)
    assert penalty["amount_cents"] == 151
    assert penalty["violation_type"] == "PRICE_ERROR"


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/device_seal_condemn_reseal_cycle
# --------------------------------------------------------------------------- #
def _seal_condemn_reseal(est, inspector, dev):
    accuracy_pass_seal(inspector, dev, "2026-03-07T09:00:00Z", "2026-03-07T10:00:00Z",
                       applied_load=3000, indicated_value=3000)          # -> SEALED
    accuracy_fail_condemn(inspector, dev, "2026-03-08T09:00:00Z", "2026-03-08T10:00:00Z",
                          applied_load=3000, indicated_value=3008)       # error 8 > maint 6 -> CONDEMNED
    # Re-test with clean reading finalizes CONDEMNED -> SEALED.
    ins3 = schedule_inspection(dev["id"], inspector["id"],
                               "2026-03-09T09:00:00Z", "2026-03-09T10:00:00Z")
    start_inspection(ins3["id"], inspector["id"])
    add_reading(ins3["id"], inspector["id"], 3000, 3000)
    return finalize_inspection(ins3["id"], inspector["id"])


def test_device_returns_to_sealed_after_repair_and_retest():
    """PRD §3.7: "When sealing proceeds, the device transitions into `SEALED` — from
    `REGISTERED`, from `OUT_OF_SERVICE`, or cyclically from `CONDEMNED` after a
    repair-and-retest — and a new `Seal` is created in `status` `ACTIVE`, linking the
    `device_id` and the `inspection_id` and carrying a server-minted sequential
    `seal_number`."

    Design: Difficulty/non_linear_state_machine/device_seal_condemn_reseal_cycle
    """
    est, inspector = bootstrap_est_inspector(est_name="Cycle Store", jurisdiction="CA-05")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CY",
                          device_class="CLASS_III")
    final = _seal_condemn_reseal(est, inspector, dev)
    assert final["outcome"] == "PASS"
    assert get_device(dev["id"])["status"] == "SEALED"


def test_condemnation_order_lifted_when_device_reseals():
    """PRD §3.7: "When the device was `CONDEMNED` before this pass, its outstanding
    condemnation order is also resolved: that `CondemnationOrder` moves from `ISSUED` to
    `LIFTED`."

    Design: Difficulty/non_linear_state_machine/device_seal_condemn_reseal_cycle
    """
    est, inspector = bootstrap_est_inspector(est_name="Cycle Store", jurisdiction="CA-05")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CY",
                          device_class="CLASS_III")
    _seal_condemn_reseal(est, inspector, dev)
    order = first_condemnation_for_device(dev["id"])
    assert order["status"] == "LIFTED"


# --------------------------------------------------------------------------- #
# Difficulty/non_linear_state_machine/inspection_finalize_pass_fail_branch
# --------------------------------------------------------------------------- #
def test_pass_finalize_creates_active_seal_and_no_penalty():
    """PRD §3.7: "When the computed outcome is `PASS`, the inspection's `outcome` is set
    to `PASS` and the inspection moves from `IN_PROGRESS` to the terminal `PASSED`."
    PRD §3.7: "a new `Seal` is created in `status` `ACTIVE`, linking the `device_id` and
    the `inspection_id` and carrying a server-minted sequential `seal_number`."

    Design: Difficulty/non_linear_state_machine/inspection_finalize_pass_fail_branch
    """
    est, inspector = bootstrap_est_inspector(est_name="Fork Store", jurisdiction="CA-06")
    devP = register_device(est["id"], device_type="SCALE", serial_number="SN-P",
                           device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, devP, "2026-03-10T09:00:00Z",
                               "2026-03-10T10:00:00Z", applied_load=3000, indicated_value=3000)
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["status"] == "PASSED" and final["outcome"] == "PASS"
    seal = first_seal_for_device(devP["id"])
    assert seal is not None and seal["status"] == "ACTIVE"
    assert penalties_for_device(devP["id"]) == [], "a passing inspection assesses no penalty"


def test_fail_finalize_creates_condemnation_and_penalty_and_no_seal():
    """PRD §3.7: "Condemnation then creates two records: a `CondemnationOrder` in
    `status` `ISSUED`, whose `reason` is a human-readable description derived from the
    failing `inspection_type`; and a `Penalty` in `status` `ASSESSED`."
    PRD §3.7: "a failing accuracy or complaint re-test records `OUT_OF_TOLERANCE`".

    Design: Difficulty/non_linear_state_machine/inspection_finalize_pass_fail_branch
    """
    est, inspector = bootstrap_est_inspector(est_name="Fork Store", jurisdiction="CA-06")
    devF = register_device(est["id"], device_type="SCALE", serial_number="SN-F",
                           device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, devF, "2026-03-11T09:00:00Z",
                               "2026-03-11T10:00:00Z", applied_load=3000, indicated_value=3005)
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["status"] == "FAILED" and final["outcome"] == "FAIL"
    order = first_condemnation_for_device(devF["id"])
    assert order is not None and order["status"] == "ISSUED"
    penalty = first_penalty_for_device(devF["id"])
    assert penalty is not None and penalty["violation_type"] == "OUT_OF_TOLERANCE"
    assert seals_for_device(devF["id"]) == [], "a failing inspection creates no seal"


# --------------------------------------------------------------------------- #
# Difficulty/transitive_cascade/fail_condemn_penalty_balance_depth3
# --------------------------------------------------------------------------- #
def test_fail_condemns_device_and_assesses_out_of_tolerance_penalty():
    """PRD §3.7: "For an `OUT_OF_TOLERANCE` or `OPERATING_CONDEMNED` penalty, the amount
    is a flat base multiplied by the repeat-offense multiplier and rounded half up to
    whole cents. The base is 5000 cents for `OUT_OF_TOLERANCE` and 20000 cents for
    `OPERATING_CONDEMNED`."
    PRD §3.7: "The multiplier is 1.0 when there are no prior condemnations, 1.5 when
    there are one or two prior condemnations, and 2.0 when there are three or more."

    Design: Difficulty/transitive_cascade/fail_condemn_penalty_balance_depth3
    """
    est, inspector = bootstrap_est_inspector(est_name="Casc A Store", jurisdiction="CA-07")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CA",
                          device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev, "2026-03-12T09:00:00Z", "2026-03-12T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    assert get_device(dev["id"])["status"] == "CONDEMNED"
    order = first_condemnation_for_device(dev["id"])
    assert order["status"] == "ISSUED"
    penalty = first_penalty_for_device(dev["id"])
    assert penalty["violation_type"] == "OUT_OF_TOLERANCE"
    assert penalty["amount_cents"] == 5000  # base 5000 * multiplier 1.0


def test_penalty_creation_raises_establishment_balance():
    """PRD §2.8: "The `balance_due_cents` of an establishment is the sum of the
    `amount_due_cents` of all of that establishment's fee invoices whose `status` is
    `DUE`, plus the sum of the `amount_cents` of all of that establishment's penalties
    whose `status` is `ASSESSED`."
    PRD §3.7: "Creating the penalty recomputes the owning establishment's
    `balance_due_cents` so that the newly assessed amount is reflected."

    Design: Difficulty/transitive_cascade/fail_condemn_penalty_balance_depth3
    """
    # Default clock Q1: SCALE registration fee is the full 12000 (DUE).
    est, inspector = bootstrap_est_inspector(est_name="Casc A Store", jurisdiction="CA-07")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-CA",
                          device_class="CLASS_III")
    assert get_establishment(est["id"])["balance_due_cents"] == 12000
    accuracy_fail_condemn(inspector, dev, "2026-03-12T09:00:00Z", "2026-03-12T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    assert get_establishment(est["id"])["balance_due_cents"] == 17000  # 12000 fee + 5000 penalty


# --------------------------------------------------------------------------- #
# Corner/calculations/penalty_repeat_multiplier_second_condemnation
# --------------------------------------------------------------------------- #
def test_second_condemnation_applies_repeat_multiplier_1_5():
    """PRD §3.7: "The multiplier is 1.0 when there are no prior condemnations, 1.5 when
    there are one or two prior condemnations, and 2.0 when there are three or more."

    Design: Corner/calculations/penalty_repeat_multiplier_second_condemnation
    """
    est, inspector = bootstrap_est_inspector(est_name="Mult Store", jurisdiction="CA-32")
    dev1 = register_device(est["id"], device_type="SCALE", serial_number="SN-M1",
                           device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev1, "2026-03-27T09:00:00Z", "2026-03-27T10:00:00Z",
                          applied_load=3000, indicated_value=3004)  # prior count -> 1
    dev2 = register_device(est["id"], device_type="SCALE", serial_number="SN-M2",
                           device_class="CLASS_III")
    accuracy_fail_condemn(inspector, dev2, "2026-03-28T09:00:00Z", "2026-03-28T10:00:00Z",
                          applied_load=3000, indicated_value=3004)
    penalty2 = first_penalty_for_device(dev2["id"])
    assert penalty2["amount_cents"] == 7500  # round(5000 * 1.5)


# --------------------------------------------------------------------------- #
# Corner/endpoints/seals_reverse_lookup_by_device
# --------------------------------------------------------------------------- #
def test_seal_reverse_lookup_by_device_returns_single_active_seal():
    """PRD §3.7: "a new `Seal` is created in `status` `ACTIVE`, linking the `device_id`
    and the `inspection_id` and carrying a server-minted sequential `seal_number`."

    Design: Corner/endpoints/seals_reverse_lookup_by_device
    """
    est, inspector = bootstrap_est_inspector(est_name="SealLk Store", jurisdiction="CA-46")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-SEALLK",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-04-08T09:00:00Z", "2026-04-08T10:00:00Z",
                       applied_load=3000, indicated_value=3000)
    seals = seals_for_device(dev["id"])
    assert len(seals) == 1
    assert seals[0]["status"] == "ACTIVE"
