"""Recall cascades, QC-failure contamination cascade, compensating invariants,
the recall reopen cycle, and the rolling anticipatory ledger.

These exercise the deepest cross-entity behavior: a depth-3 recall cascade
(batch → finished preparations → prescription), the depth-2 QC-failure cascade
(test → ingredient lots), grams- and units-conservation invariants, the cyclic
recall machine, and the aggregate-capacity anticipatory window.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_compounding_headers,
    make_qa_headers,
    create_facility,
    create_mfr,
    create_lot,
    create_prescription,
    create_compiled_batch,
    create_started_batch,
    create_released_batch,
    quarantine_batch,
    add_passing_required_qc,
    list_finished_preparations,
    dispense_prescription_unit,
    setup_503b_released_office_use_batch,
    create_qc_test_payload,
    record_qc_payload,
    create_recall_payload,
    compile_payload,
    release_payload,
    set_clock_payload,
)

COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]
ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispensing_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/recall_cascade_batch_to_prep_to_prescription_depth3
# ─────────────────────────────────────────────────────────────────────────────

def test_recall_cascades_batch_preps_and_prescription(api):
    """PRD §3.10: "The batch itself transitions from RELEASED to RECALLED. Every
    finished preparation of the batch has its dispense_status set to RECALLED,
    overriding whatever IN_INVENTORY or DISPENSED value it held. ... For every unit
    that had been dispensed against a 503A prescription, that prescription's
    units_dispensed is decremented by one, and if the prescription had been FILLED
    it reverts to ACTIVE."

    Design: Difficulty/transitive_cascade/recall_cascade_batch_to_prep_to_prescription_depth3
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Naltrexone 4.5mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=2,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Robin Vale",
                             units_prescribed=2)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 2, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    preps = list_finished_preparations(batch["id"])
    dispense_prescription_unit(facility["id"], preps[0]["id"], rx["id"])
    dispense_prescription_unit(facility["id"], preps[1]["id"], rx["id"])
    filled = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert filled["status"] == "FILLED" and filled["units_dispensed"] == 2

    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="POTENCY_OOS", classification="CLASS_I"), QA), 201)

    batch_after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert batch_after["status"] == "RECALLED"
    for p in list_finished_preparations(batch["id"]):
        assert p["dispense_status"] == "RECALLED"
    rx_after = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert rx_after["units_dispensed"] == 0
    assert rx_after["status"] == "ACTIVE"
    assert recall["units_in_scope"] == 2


def test_recall_overrides_in_inventory_preps_to_recalled(api):
    """PRD §3.10: "Every finished preparation of the batch has its dispense_status
    set to RECALLED, overriding whatever IN_INVENTORY or DISPENSED value it held.
    The recall snapshots units_in_scope as the count of finished preparations
    belonging to the batch at the moment of initiation."

    Design: Difficulty/transitive_cascade/recall_cascade_batch_to_prep_to_prescription_depth3
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Naltrexone 4.5mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=2,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=2)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 2, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    preps = list_finished_preparations(batch["id"])
    # No dispense: both preps remain IN_INVENTORY before the recall.
    assert all(p["dispense_status"] == "IN_INVENTORY" for p in preps)

    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="STERILITY_FAILURE", classification="CLASS_I"), QA), 201)
    assert recall["units_in_scope"] == 2
    for p in list_finished_preparations(batch["id"]):
        assert p["dispense_status"] == "RECALLED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/qc_fail_cascade_test_to_lot_quarantine_depth2
# ─────────────────────────────────────────────────────────────────────────────

def test_failed_sterility_test_quarantines_charged_lots(api):
    """PRD §3.7: "When a recorded test of type STERILITY or ENDOTOXIN evaluates to
    FAILED and the parent batch's formula is sterile, the system quarantines every
    ingredient lot charged to that batch whose status is currently AVAILABLE,
    moving each such lot from AVAILABLE to QUARANTINED."

    Design: Difficulty/transitive_cascade/qc_fail_cascade_test_to_lot_quarantine_depth2
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Vancomycin 5mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE")
    ster = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "STERILITY"), QA))
    api.begin_qc_test(ster["id"], QA)

    recorded = validate_success(
        api.record_qc_test(ster["id"], record_qc_payload(pass_flag=False), QA), 200)
    assert recorded["result"] == "FAILED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert lot_after["status"] == "QUARANTINED"


def test_failed_endotoxin_test_quarantines_charged_lots(api):
    """PRD §3.7: "When a recorded test of type STERILITY or ENDOTOXIN evaluates to
    FAILED and the parent batch's formula is sterile, the system quarantines every
    ingredient lot charged to that batch whose status is currently AVAILABLE,
    moving each such lot from AVAILABLE to QUARANTINED."

    Design: Difficulty/transitive_cascade/qc_fail_cascade_test_to_lot_quarantine_depth2
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Vancomycin 5mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], labeled_potency_pct=99.4, initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE")
    endo = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "ENDOTOXIN"), QA))
    api.begin_qc_test(endo["id"], QA)
    # projected = 1000 * (9940/100) = huge → FAILED for the injectable 175 ceiling.
    recorded = validate_success(
        api.record_qc_test(endo["id"], record_qc_payload(measured_value=1000), QA), 200)
    assert recorded["result"] == "FAILED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert lot_after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/recall_in_progress_reopen_cycle_back_to_initiated
# ─────────────────────────────────────────────────────────────────────────────

def test_recall_reopen_cycles_back_to_initiated(api):
    """PRD §3.10: "A recall under reconciliation may be reopened to widen scope,
    moving it from IN_PROGRESS back to INITIATED (it must be IN_PROGRESS, else
    ERR_RECALL_NOT_IN_STATE)."

    Design: Difficulty/non_linear_state_machine/recall_in_progress_reopen_cycle_back_to_initiated
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Clonidine 0.1mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=10,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=10)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 10, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="POTENCY_OOS", classification="CLASS_II"), QA), 201)
    validate_success(api.advance_recall(recall["id"], QA), 200)

    reopened = validate_success(api.reopen_recall(recall["id"], QA), 200)
    assert reopened["status"] == "INITIATED"


def test_recall_reopen_cycle_can_be_re_advanced(api):
    """PRD §3.10: "Advancing a recall moves it from INITIATED to IN_PROGRESS (it
    must be INITIATED, else ERR_RECALL_NOT_IN_STATE)."

    Design: Difficulty/non_linear_state_machine/recall_in_progress_reopen_cycle_back_to_initiated
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Clonidine 0.1mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=10,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=10)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 10, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="POTENCY_OOS", classification="CLASS_II"), QA), 201)
    api.advance_recall(recall["id"], QA)
    api.reopen_recall(recall["id"], QA)

    # After the reopen returns the recall to INITIATED, advance is valid again.
    re_advanced = validate_success(api.advance_recall(recall["id"], QA), 200)
    assert re_advanced["status"] == "IN_PROGRESS"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/reject_restocks_lot_grams_conserves_total_grams
# ─────────────────────────────────────────────────────────────────────────────

def test_reject_restocks_lot_grams_to_initial(api):
    """PRD §3.6: "When all hold, the start succeeds and, as its side effect,
    decrements each charged lot's remaining_grams by the corresponding grams_used."
    PRD §3.8: "as a compensating restock that conserves total grams, restores each
    charged lot's remaining_grams by the grams_used that had been consumed at
    start."

    Design: Difficulty/compensating_invariant/reject_restocks_lot_grams_conserves_total_grams
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Omeprazole 2mg/mL Susp",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=14,
                     theoretical_yield_units=5, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]}, grams_used=10)
    mid = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert mid["remaining_grams"] == pytest.approx(40.0, abs=0.0001)
    quarantine_batch(batch["id"])

    rejected = validate_success(
        api.reject_batch(batch["id"], make_qa_headers("qa-user-2")), 200)
    assert rejected["status"] == "REJECTED"
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert lot_after["remaining_grams"] == pytest.approx(50.0, abs=0.0001)


def test_reject_after_two_starts_charge_conserves_grams_per_lot(api):
    """PRD §3.3: "remaining_grams ... equals initial_grams minus the sum of
    grams_used across every usage row of this lot that belongs to a batch which is
    neither in DRAFT nor REJECTED status." PRD §3.8: "as a compensating restock
    that conserves total grams, restores each charged lot's remaining_grams by the
    grams_used that had been consumed at start."

    Design: Difficulty/compensating_invariant/reject_restocks_lot_grams_conserves_total_grams
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Omeprazole 2mg/mL Susp",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=14,
                     theoretical_yield_units=5, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    # Charge a distinct 7 grams so the restore amount differs from the default 10.
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]}, grams_used=7)
    mid = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert mid["remaining_grams"] == pytest.approx(43.0, abs=0.0001)

    api.reject_batch(batch["id"], make_qa_headers("qa-user-2"))
    after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert after["remaining_grams"] == pytest.approx(50.0, abs=0.0001)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/recall_then_decrement_conserves_prescription_units_dispensed
# ─────────────────────────────────────────────────────────────────────────────

def test_recall_decrements_dispensed_units_back_to_zero(api):
    """PRD §3.9: "For a 503A patient unit, the dispense additionally increments the
    linked prescription's units_dispensed by one". PRD §3.10: "For every unit that
    had been dispensed against a 503A prescription, that prescription's
    units_dispensed is decremented by one, and if the prescription had been FILLED
    it reverts to ACTIVE."

    Design: Difficulty/compensating_invariant/recall_then_decrement_conserves_prescription_units_dispensed
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Metoprolol 5mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=1,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Lane Cruz",
                             units_prescribed=2)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 1, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]
    dispense_prescription_unit(facility["id"], prep["id"], rx["id"])
    mid = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert mid["units_dispensed"] == 1 and mid["status"] == "ACTIVE"

    api.create_recall(create_recall_payload(facility["id"], batch["id"],
                      reason="LABELING_ERROR", classification="CLASS_III"), QA)

    rx_after = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert rx_after["units_dispensed"] == 0
    assert rx_after["status"] == "ACTIVE"
    prep_after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert prep_after["dispense_status"] == "RECALLED"


def test_dispensed_unit_recall_keeps_prescription_active_at_partial_fill(api):
    """PRD §3.9: "if that brings units_dispensed to equal units_prescribed, the
    prescription transitions from ACTIVE to FILLED." PRD §3.10: "For every unit that
    had been dispensed against a 503A prescription, that prescription's
    units_dispensed is decremented by one".

    Design: Difficulty/compensating_invariant/recall_then_decrement_conserves_prescription_units_dispensed
    """
    # units_prescribed=2 but only 1 unit dispensed → prescription never FILLED,
    # so the recall decrement returns units_dispensed to 0 with status still ACTIVE.
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Metoprolol 5mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=1,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=2)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 1, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]
    dispense_prescription_unit(facility["id"], prep["id"], rx["id"])

    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="LABELING_ERROR", classification="CLASS_III"), QA), 201)
    assert recall["units_in_scope"] == 1
    rx_after = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert rx_after["units_dispensed"] == 0
    assert rx_after["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/anticipatory_rolling_window_aggregate_capacity_overlap
# ─────────────────────────────────────────────────────────────────────────────

def test_second_office_use_release_over_window_capacity_rejected(api):
    """PRD §3.8: "Finally, for an OFFICE_USE batch only, the anticipatory gate: the
    formula's anticipatory ledger remaining_units must be at least the batch's
    actual_yield_units, or the release is rejected with
    ERR_ANTICIPATORY_LIMIT_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/anticipatory_rolling_window_aggregate_capacity_overlap
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Lidocaine 2% Inj", dosage_form="ORAL_LIQUID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=120,
                     anticipatory_max_units=200, anticipatory_window_days=30)
    lot1 = create_lot(facility["id"], lot_number="L-1", initial_grams=200,
                      expiration_utc="2030-01-01T00:00:00.000Z")
    lot2 = create_lot(facility["id"], lot_number="L-2", initial_grams=200,
                      expiration_utc="2030-01-01T00:00:00.000Z")
    # First release consumes 120 of 200.
    create_released_batch(facility["id"], mfr["id"], lot1["id"], 120,
                          purpose="OFFICE_USE")
    # Second batch: 115 units (variance vs 120 theoretical = -4.17%, within the
    # ±5.00% yield band so compile succeeds), but 115 > remaining capacity of 80
    # (200 cap − 120 consumed), so release trips the anticipatory gate.
    batch2 = create_compiled_batch(
        facility["id"], mfr["id"], lot2["id"], 115, purpose="OFFICE_USE",
        compiler_id="comp-user-1")
    add_passing_required_qc(batch2["id"], is_sterile=False)
    quarantine_batch(batch2["id"])
    cur = get_success_data(api.get_batch(batch2["id"], QA))

    res = api.release_batch(batch2["id"], release_payload(cur["version"]),
                            make_qa_headers("qa-user-3"))
    validate_error(res, "ERR_ANTICIPATORY_LIMIT_EXCEEDED", expected_status=409)
    after = validate_success(api.get_batch(batch2["id"], QA), 200)
    assert after["status"] == "QUARANTINED"
    ledger = validate_success(api.get_anticipatory_ledger_for_mfr(mfr["id"], QA), 200)
    assert ledger["consumed_units"] == 120
    assert ledger["remaining_units"] == 80


def test_in_window_office_use_release_consumes_ledger_capacity(api):
    """PRD §3.2: "The consumed_units is the sum of actual_yield_units over every
    office-use batch of this formula that is currently in RELEASED status and whose
    released_at_utc falls on or after window_start_utc". PRD §3.8: "For an
    OFFICE_USE batch, release also recomputes the formula's anticipatory ledger
    consumed_units and remaining_units so the just-released yield is reflected in
    the rolling window."

    Design: Difficulty/resource_temporal_overlap/anticipatory_rolling_window_aggregate_capacity_overlap
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Lidocaine 2% Inj", dosage_form="ORAL_LIQUID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=120,
                     anticipatory_max_units=200, anticipatory_window_days=30)
    lot = create_lot(facility["id"], initial_grams=200,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    create_released_batch(facility["id"], mfr["id"], lot["id"], 120,
                          purpose="OFFICE_USE")

    # The single in-window 120-unit release sits inside the rolling window.
    ledger = validate_success(api.get_anticipatory_ledger_for_mfr(mfr["id"], QA), 200)
    assert ledger["consumed_units"] == 120
    assert ledger["remaining_units"] == 80


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/anticipatory_window_excludes_out_of_window_release
# ─────────────────────────────────────────────────────────────────────────────

def test_anticipatory_window_excludes_out_of_window_release(api):
    """PRD §3.2: "The consumed_units is the sum of actual_yield_units over every
    office-use batch of this formula that is currently in RELEASED status and whose
    released_at_utc falls on or after window_start_utc ... The window_start_utc is
    the left edge of the rolling window, computed as the facility's current_utc
    minus the formula's anticipatory_window_days."

    Design: Corner/calculations/anticipatory_window_excludes_out_of_window_release
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Win F", dosage_form="ORAL_LIQUID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=120,
                     anticipatory_max_units=200, anticipatory_window_days=30)
    lot = create_lot(facility["id"], initial_grams=200,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    create_released_batch(facility["id"], mfr["id"], lot["id"], 120,
                          purpose="OFFICE_USE")
    # Advance clock to 2026-08-01 (61 days later → release at 2026-06-01 out of 30-day window)
    api.set_clock(facility["id"], set_clock_payload("2026-08-01T00:00:00.000Z"), ADMIN)

    ledger = validate_success(api.get_anticipatory_ledger_for_mfr(mfr["id"], COMP), 200)
    assert ledger["consumed_units"] == 0
    assert ledger["remaining_units"] == 200


# ─────────────────────────────────────────────────────────────────────────────
# Corner/endpoints/get_anticipatory_ledger_computed_read_recomputes
# ─────────────────────────────────────────────────────────────────────────────

def test_get_anticipatory_ledger_by_id_recomputes(api):
    """PRD §3.2: "The ledger can be read directly, and it can also be reached as a
    computed read for a given formula; in both cases the three derived quantities
    are recomputed against the current clock at the moment of the read."

    Design: Corner/endpoints/get_anticipatory_ledger_computed_read_recomputes
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=200, anticipatory_window_days=30)
    listing = validate_success(
        api.list_anticipatory_ledgers(
            COMP, params={"master_formulation_record_id": mfr["id"]}), 200)
    ledger_id = listing[0]["id"]

    ledger = validate_success(api.get_anticipatory_ledger(ledger_id, COMP), 200)
    assert ledger["consumed_units"] == 0
    assert ledger["remaining_units"] == 200


# ─────────────────────────────────────────────────────────────────────────────
# Corner/endpoints/recall_full_reconcile_close_lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def test_recall_reconcile_and_close_lifecycle(api):
    """PRD §3.10: "Reconciling a recall recomputes units_reconciled as the count of
    in-scope units now in RECALLED dispense status and moves the recall from
    IN_PROGRESS to RECONCILED — but only when units_reconciled equals
    units_in_scope". and "closing a recall moves it from RECONCILED to CLOSED ...
    CLOSED is terminal."

    Design: Corner/endpoints/recall_full_reconcile_close_lifecycle
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=1,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=1)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 1, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    recall = validate_success(
        api.create_recall(create_recall_payload(facility["id"], batch["id"],
                          reason="POTENCY_OOS", classification="CLASS_II"), QA), 201)
    api.advance_recall(recall["id"], QA)
    reconciled = validate_success(api.reconcile_recall(recall["id"], QA), 200)
    assert reconciled["units_in_scope"] == 1
    assert reconciled["units_reconciled"] == 1

    closed = validate_success(api.close_recall(recall["id"], QA), 200)
    assert closed["status"] == "CLOSED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/errors/err_batch_not_released_on_recall_of_draft_batch
# ─────────────────────────────────────────────────────────────────────────────

def test_recall_of_draft_batch_rejected(api):
    """PRD §3.10: "The target batch must be RELEASED, or the initiation is rejected
    with ERR_BATCH_NOT_RELEASED."

    Design: Corner/errors/err_batch_not_released_on_recall_of_draft_batch
    """
    facility = create_facility("503B", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    batch = validate_success(
        api.create_batch(
            {"facility_id": facility["id"], "master_formulation_record_id": mfr["id"],
             "purpose": "OFFICE_USE"}, COMP), 201)

    res = api.create_recall(create_recall_payload(facility["id"], batch["id"],
                            reason="LABELING_ERROR", classification="CLASS_III"), QA)
    validate_error(res, "ERR_BATCH_NOT_RELEASED", expected_status=409)
