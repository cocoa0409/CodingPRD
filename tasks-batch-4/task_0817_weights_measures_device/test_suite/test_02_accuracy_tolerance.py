"""Accuracy-test tolerance evaluation: acceptance vs maintenance, tiering, boundary.

Covers difficulty instances accuracy_acceptance_vs_maintenance_tolerance,
accuracy_tiered_tolerance_mode_a, and accuracy_error_equals_tolerance_passes.
"""
from test_helpers import (
    bootstrap_est_inspector, register_device,
    accuracy_pass_seal, in_progress_accuracy, schedule_inspection,
    start_inspection, add_reading, finalize_inspection, get_device,
)


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/accuracy_acceptance_vs_maintenance_tolerance
# --------------------------------------------------------------------------- #
def test_four_gram_error_passes_on_in_service_sealed_device():
    """PRD §3.5: "For a device already in service — one whose `status` is `SEALED`,
    `CONDEMNED`, or `OUT_OF_SERVICE` — the looser maintenance tolerance applies as-is."
    PRD §3.5: "For a `CLASS_III` device the maintenance tolerance is 6 grams when the
    applied load is 5000 grams or less, 12 grams when the load is greater than 5000
    grams and up to and including 20000 grams, and 20 grams when the load is greater
    than 20000 grams."

    Design: Difficulty/dual_variant_calc/accuracy_acceptance_vs_maintenance_tolerance
    """
    est, inspector = bootstrap_est_inspector(est_name="Tol Store", jurisdiction="CA-02")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-A",
                          device_class="CLASS_III")
    accuracy_pass_seal(inspector, dev, "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z")
    assert get_device(dev["id"])["status"] == "SEALED"

    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-03T09:00:00Z", "2026-03-03T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])
    add_reading(ins["id"], inspector["id"], 3000, 3004)  # error 4 <= maintenance 6
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["outcome"] == "PASS", "error 4 within maintenance tol 6 must PASS"
    assert get_device(dev["id"])["status"] == "SEALED"


def test_four_gram_error_fails_on_registered_device():
    """PRD §3.5: "For a brand-new, never-sealed device — one whose `status` is still
    `REGISTERED` — the stricter **acceptance tolerance** applies, equal to exactly half
    of the maintenance tolerance (the maintenance constants are all even, so the halving
    is exact)."
    PRD §3.5: "The inspection's computed outcome is `PASS` when every reading passes and
    `FAIL` when any reading exceeds its tolerance."

    Design: Difficulty/dual_variant_calc/accuracy_acceptance_vs_maintenance_tolerance
    """
    est, inspector = bootstrap_est_inspector(est_name="Tol Store", jurisdiction="CA-02")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-B",
                          device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, dev, "2026-03-04T09:00:00Z",
                               "2026-03-04T10:00:00Z", applied_load=3000, indicated_value=3004)
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["outcome"] == "FAIL", "error 4 exceeds acceptance tol 3 must FAIL"
    assert get_device(dev["id"])["status"] == "CONDEMNED"


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/accuracy_tiered_tolerance_mode_a
# --------------------------------------------------------------------------- #
def test_load_8000_error_12_fails_acceptance_tolerance():
    """PRD §3.5: "For a `CLASS_III` device the maintenance tolerance is 6 grams when the
    applied load is 5000 grams or less, 12 grams when the load is greater than 5000
    grams and up to and including 20000 grams, and 20 grams when the load is greater
    than 20000 grams."
    PRD §3.4: "The server derives `error_grams` for the reading as the absolute
    difference between the indicated value and the applied load."

    Design: Difficulty/combinatorial_formula/accuracy_tiered_tolerance_mode_a
    """
    est, inspector = bootstrap_est_inspector(est_name="Tier Store", jurisdiction="CA-03")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-T",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-05T09:00:00Z", "2026-03-05T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])
    reading = add_reading(ins["id"], inspector["id"], 8000, 8012)  # tier 12, acceptance 6
    assert reading["error_grams"] == 12
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["outcome"] == "FAIL", "error 12 exceeds acceptance tol 6 (maint 12/2) must FAIL"


def test_load_8000_failure_condemns_registered_device():
    """PRD §3.7: "The fail drives the device to `CONDEMNED` — from `REGISTERED`, from
    `OUT_OF_SERVICE`, or from `SEALED`; a suspended establishment does not block
    condemnation."

    Design: Difficulty/combinatorial_formula/accuracy_tiered_tolerance_mode_a
    """
    est, inspector = bootstrap_est_inspector(est_name="Tier Store", jurisdiction="CA-03")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-T",
                          device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, dev, "2026-03-05T09:00:00Z",
                               "2026-03-05T10:00:00Z", applied_load=8000, indicated_value=8012)
    finalize_inspection(ins["id"], inspector["id"])
    assert get_device(dev["id"])["status"] == "CONDEMNED"


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/accuracy_error_equals_tolerance_passes
# --------------------------------------------------------------------------- #
def test_error_exactly_equal_to_tolerance_passes():
    """PRD §3.5: "A single reading passes when its `error_grams` is less than or equal
    to the applicable tolerance; equality is a pass."

    Design: Difficulty/boundary_precision_check/accuracy_error_equals_tolerance_passes
    """
    est, inspector = bootstrap_est_inspector(est_name="Bnd Store", jurisdiction="CA-11")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-BND",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-16T09:00:00Z", "2026-03-16T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])
    reading = add_reading(ins["id"], inspector["id"], 3000, 3003)  # error exactly 3 == acceptance 3
    assert reading["error_grams"] == 3
    final = finalize_inspection(ins["id"], inspector["id"])
    assert final["outcome"] == "PASS", "error exactly equal to tolerance is a PASS"


def test_error_at_tolerance_seals_device():
    """PRD §3.7: "When sealing proceeds, the device transitions into `SEALED` — from
    `REGISTERED`, from `OUT_OF_SERVICE`, or cyclically from `CONDEMNED` after a
    repair-and-retest — and a new `Seal` is created in `status` `ACTIVE`, linking the
    `device_id` and the `inspection_id` and carrying a server-minted sequential
    `seal_number`."

    Design: Difficulty/boundary_precision_check/accuracy_error_equals_tolerance_passes
    """
    est, inspector = bootstrap_est_inspector(est_name="Bnd Store", jurisdiction="CA-11")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-BND",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-16T09:00:00Z", "2026-03-16T10:00:00Z")
    start_inspection(ins["id"], inspector["id"])
    add_reading(ins["id"], inspector["id"], 3000, 3003)
    finalize_inspection(ins["id"], inspector["id"])
    assert get_device(dev["id"])["status"] == "SEALED"
