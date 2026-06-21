"""Compounding-batch state machine, QC test machine, and prescription/lot lazy expiry.

Covers the branching-with-revert reprocess cycle, the DRAFT initial state, invalid
and idempotent transitions, terminal-state lockdown, the MFR-retired start guard,
reject side effects, and the lazy clock-driven expiry transitions.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    create_facility,
    create_mfr,
    create_lot,
    create_prescription,
    create_draft_batch,
    charge_usage,
    create_started_batch,
    create_compiled_batch,
    quarantine_batch,
    add_passing_required_qc,
    list_finished_preparations,
    create_batch_ingredient_usage_payload,
    compile_payload,
    create_qc_test_payload,
    record_qc_payload,
    set_clock_payload,
)

COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]
ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispensing_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/non_linear_state_machine/batch_quarantined_reprocess_cycle_back_to_in_process
# ─────────────────────────────────────────────────────────────────────────────

def test_reprocess_returns_quarantined_batch_to_in_process(api):
    """PRD §3.6: "Reprocessing a batch returns it from QUARANTINED to IN_PROCESS so
    it can be re-compiled." and "As its side effects, reprocess voids and deletes
    all finished preparations minted by the prior compile and clears the batch's
    compiled_by_user_id, actual_yield_units, yield_variance_pct, and
    assigned_bud_utc."

    Design: Difficulty/non_linear_state_machine/batch_quarantined_reprocess_cycle_back_to_in_process
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Baclofen 10mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=50)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    assert len(list_finished_preparations(batch["id"])) == 100
    quarantine_batch(batch["id"])

    reprocessed = validate_success(api.reprocess_batch(batch["id"], COMP), 200)
    assert reprocessed["status"] == "IN_PROCESS"
    assert len(list_finished_preparations(batch["id"])) == 0, (
        "prior FinishedPreparations must be voided on reprocess")
    assert reprocessed.get("compiled_by_user_id") in (None, ""), (
        "compiled_by_user_id must be cleared on reprocess")


def test_reprocessed_batch_can_be_recompiled(api):
    """PRD §3.6: "A quarantined batch is not yet final — it may be reworked.
    Reprocessing a batch returns it from QUARANTINED to IN_PROCESS so it can be
    re-compiled."

    Design: Difficulty/non_linear_state_machine/batch_quarantined_reprocess_cycle_back_to_in_process
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Baclofen 10mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=50)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    quarantine_batch(batch["id"])
    validate_success(api.reprocess_batch(batch["id"], COMP), 200)

    # The cycle is genuine: an IN_PROCESS batch re-compiles and re-mints preps.
    recompiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(100), COMP), 200)
    assert recompiled["status"] == "COMPILED"
    assert len(list_finished_preparations(batch["id"])) == 100


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/batch_initial_state_is_draft
# ─────────────────────────────────────────────────────────────────────────────

def test_new_batch_starts_in_draft_with_yield_snapshot(api):
    """PRD §3.6: "The central production entity is the Compounding Batch, opened in
    DRAFT status by a CompoundingPharmacist." and "At creation the batch also
    snapshots the formula's theoretical_yield_units into its own
    theoretical_yield_units field, freezing the nominal yield as of batch creation."

    Design: Corner/state_machines/batch_initial_state_is_draft
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    batch = validate_success(
        api.create_batch(
            {"facility_id": facility["id"], "master_formulation_record_id": mfr["id"],
             "purpose": "OFFICE_USE"}, COMP), 201)
    assert batch["status"] == "DRAFT"
    assert batch["theoretical_yield_units"] == 100
    assert batch["version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/compile_from_draft_rejected_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_compile_from_draft_rejected(api):
    """PRD §3.6: "A CompoundingPharmacist compiles an IN_PROCESS batch, supplying
    the operator-counted actual_yield_units (zero or more) in the body; the batch
    must be IN_PROCESS or the compile is rejected with ERR_BATCH_NOT_IN_STATE".

    Design: Corner/state_machines/compile_from_draft_rejected_invalid_state
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    charge_usage(batch["id"], lot["id"], grams_used=10)

    res = api.compile_batch(batch["id"], compile_payload(100), COMP)
    validate_error(res, "ERR_BATCH_NOT_IN_STATE", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], COMP), 200)
    assert after["status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/reject_from_terminal_rejected_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_second_reject_on_terminal_batch_rejected(api):
    """PRD §3.8: "A QualityAssurancePharmacist may reject a batch that is in either
    QUARANTINED or COMPILED status, moving it to REJECTED; a reject attempt from
    any other state is rejected with ERR_BATCH_NOT_IN_STATE. ... Both REJECTED and
    RECALLED are terminal batch states."

    Design: Corner/state_machines/reject_from_terminal_rejected_returns_invalid_state
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    validate_success(api.reject_batch(batch["id"], QA), 200)

    res = api.reject_batch(batch["id"], QA)
    validate_error(res, "ERR_BATCH_NOT_IN_STATE", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "REJECTED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/start_idempotency_second_start_returns_invalid_state
# ─────────────────────────────────────────────────────────────────────────────

def test_second_start_rejected_and_grams_not_double_decremented(api):
    """PRD §3.6: "The batch must currently be DRAFT, or the start is rejected with
    ERR_BATCH_NOT_IN_STATE." and "When all hold, the start succeeds and, as its
    side effect, decrements each charged lot's remaining_grams by the corresponding
    grams_used."

    Design: Corner/state_machines/start_idempotency_second_start_returns_invalid_state
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE", grams_used=10)

    res = api.start_batch(batch["id"], COMP)
    validate_error(res, "ERR_BATCH_NOT_IN_STATE", expected_status=409)
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert lot_after["remaining_grams"] == pytest.approx(40.0, abs=0.0001), (
        "remaining_grams must not be double-decremented to 30")


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/start_blocked_when_mfr_retired_guarded_transition
# ─────────────────────────────────────────────────────────────────────────────

def test_start_blocked_when_mfr_retired(api):
    """PRD §3.2: "a RETIRED record accepts no new batch starts, and an attempt to
    start a batch against a retired formula is rejected with ERR_MFR_RETIRED."

    Design: Corner/state_machines/start_blocked_when_mfr_retired_guarded_transition
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    charge_usage(batch["id"], lot["id"], grams_used=10)
    validate_success(api.retire_mfr(mfr["id"], COMP), 200)

    res = api.start_batch(batch["id"], COMP)
    validate_error(res, "ERR_MFR_RETIRED", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], COMP), 200)
    assert after["status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/reject_from_compiled_rejects_preps_side_effect
# ─────────────────────────────────────────────────────────────────────────────

def test_reject_from_compiled_rejects_preps_and_restocks_lot(api):
    """PRD §3.8: "Rejection transitions every child finished preparation's qc_status
    to QC_REJECTED and, as a compensating restock that conserves total grams,
    restores each charged lot's remaining_grams by the grams_used that had been
    consumed at start."

    Design: Corner/state_machines/reject_from_compiled_rejects_preps_side_effect
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    rejected = validate_success(api.reject_batch(batch["id"], QA), 200)
    assert rejected["status"] == "REJECTED"
    preps = list_finished_preparations(batch["id"])
    assert preps and all(p["qc_status"] == "QC_REJECTED" for p in preps)
    lot_after = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert lot_after["remaining_grams"] == pytest.approx(50.0, abs=0.0001)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/prescription_lazy_expiry_after_validity_days
# ─────────────────────────────────────────────────────────────────────────────

def test_prescription_lazily_expires_after_180_days(api):
    """PRD §3.5: "when the facility's current_utc is strictly later than the
    written_utc plus 180 days, the prescription is considered EXPIRED. This expiry
    is evaluated lazily whenever the prescription is read or used as a precondition
    of a dispense."

    Design: Corner/state_machines/prescription_lazy_expiry_after_validity_days
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5,
                             written_utc="2026-06-01T00:00:00.000Z")
    api.set_clock(facility["id"], set_clock_payload("2026-12-01T00:00:00.000Z"), ADMIN)

    read = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert read["status"] == "EXPIRED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/ingredient_lot_lazy_expired_on_read
# ─────────────────────────────────────────────────────────────────────────────

def test_ingredient_lot_lazily_expires_on_read(api):
    """PRD §3.3: "Expiry is evaluated lazily against the facility clock: reading a
    lot whose expiration_utc is at or before the facility's current_utc, and whose
    status was AVAILABLE, lazily transitions that lot to EXPIRED."

    Design: Corner/state_machines/ingredient_lot_lazy_expired_on_read
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2026-06-10T00:00:00.000Z")
    api.set_clock(facility["id"], set_clock_payload("2026-06-11T00:00:00.000Z"), ADMIN)

    read = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert read["status"] == "EXPIRED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/lot_release_quarantine_back_to_available
# ─────────────────────────────────────────────────────────────────────────────

def test_quarantined_lot_returns_to_available(api):
    """PRD §3.3: "a QualityAssurancePharmacist may return a QUARANTINED lot to
    AVAILABLE after investigation."

    Design: Corner/state_machines/lot_release_quarantine_back_to_available
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Sterile F", dosage_form="STERILE_AQUEOUS",
                     default_bud_days_nonsterile=1, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE")
    # Fail a sterility test → cascade quarantines the AVAILABLE charged lot.
    ster = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "STERILITY"), QA))
    api.begin_qc_test(ster["id"], QA)
    api.record_qc_test(ster["id"], record_qc_payload(pass_flag=False), QA)
    quarantined = validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)
    assert quarantined["status"] == "QUARANTINED"

    released = validate_success(api.release_quarantine_lot(lot["id"], QA), 200)
    assert released["status"] == "AVAILABLE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/state_machines/prescription_cancel_with_dispenses_blocked
# ─────────────────────────────────────────────────────────────────────────────

def test_cancel_prescription_with_dispenses_blocked(api):
    """PRD §3.5: "a cancel attempt when units_dispensed is greater than zero is
    rejected with ERR_PRESCRIPTION_HAS_DISPENSES."

    Design: Corner/state_machines/prescription_cancel_with_dispenses_blocked
    """
    from test_helpers import create_released_batch, dispense_prescription_unit
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=1,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Rx One",
                             units_prescribed=2)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 1, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]
    dispense_prescription_unit(facility["id"], prep["id"], rx["id"])

    res = api.cancel_prescription(rx["id"], DISP)
    validate_error(res, "ERR_PRESCRIPTION_HAS_DISPENSES", expected_status=409)
    after = validate_success(api.get_prescription(rx["id"], DISP), 200)
    assert after["status"] == "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/consistency_model/immediate_consistency_compile_mints_preps_in_same_request
# ─────────────────────────────────────────────────────────────────────────────

def test_compile_mints_preps_visible_immediately(api):
    """PRD §3.6: "When compile succeeds, the system mints exactly actual_yield_units
    Finished Preparations".

    Design: Corner/consistency_model/immediate_consistency_compile_mints_preps_in_same_request
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=3,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")
    api.compile_batch(batch["id"], compile_payload(3), COMP)

    data, meta = (lambda r: (r.json()["data"], r.json()["meta"]))(
        api.list_finished_preparations(
            COMP, params={"compounding_batch_id": batch["id"], "limit": 100}))
    assert meta["total_count"] == 3, "all 3 preps visible immediately after compile"
