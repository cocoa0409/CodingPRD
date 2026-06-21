"""Dispensing channel coherence, cross-entity state dependencies, beyond-use
boundary, purpose/prescription coherence, and the unit-state dispense gates.

These exercise the FinishedPreparation dispense dimension and its dependence on a
distinct second entity (the charged lot's status, the referenced prescription's
status, the unit's beyond-use date and qc/dispense status).
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
    create_compiled_batch,
    create_started_batch,
    create_draft_batch,
    create_released_batch,
    charge_usage,
    list_finished_preparations,
    create_qc_test_payload,
    record_qc_payload,
    create_dispense_payload,
    create_batch_payload,
    compile_payload,
    set_clock_payload,
)

COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]
ADMIN = TEST_USERS["admin_headers"]
DISP = TEST_USERS["dispensing_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/batch_start_blocked_by_quarantined_lot_pair_batch_lot
# ─────────────────────────────────────────────────────────────────────────────

def test_start_blocked_by_quarantined_lot(api):
    """PRD §3.6: "Every charged lot must be in AVAILABLE status with an
    expiration_utc strictly later than the facility's current_utc, or the start is
    rejected with ERR_LOT_NOT_AVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/batch_start_blocked_by_quarantined_lot_pair_batch_lot
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Cefazolin 10mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Cefazolin", lot_number="CZ-1",
                     initial_grams=100, expiration_utc="2030-01-01T00:00:00.000Z")
    # First batch quarantines the lot via a failed sterility test.
    batch1 = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE")
    ster = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch1["id"], "STERILITY"), QA))
    api.begin_qc_test(ster["id"], QA)
    api.record_qc_test(ster["id"], record_qc_payload(pass_flag=False), QA)
    assert validate_success(api.get_ingredient_lot(lot["id"], COMP), 200)["status"] == "QUARANTINED"

    # Second batch charges the now-quarantined lot, then tries to start.
    batch2 = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    charge_usage(batch2["id"], lot["id"], grams_used=10)
    res = api.start_batch(batch2["id"], COMP)
    validate_error(res, "ERR_LOT_NOT_AVAILABLE", expected_status=409)
    after = validate_success(api.get_batch(batch2["id"], COMP), 200)
    assert after["status"] == "DRAFT"


def test_start_succeeds_once_quarantined_lot_returned_to_available(api):
    """PRD §3.3: "a QualityAssurancePharmacist may return a QUARANTINED lot to
    AVAILABLE after investigation." PRD §3.6: "Every charged lot must be in
    AVAILABLE status with an expiration_utc strictly later than the facility's
    current_utc, or the start is rejected with ERR_LOT_NOT_AVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/batch_start_blocked_by_quarantined_lot_pair_batch_lot
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Cefazolin 10mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Cefazolin", lot_number="CZ-1",
                     initial_grams=100, expiration_utc="2030-01-01T00:00:00.000Z")
    batch1 = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE")
    ster = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch1["id"], "STERILITY"), QA))
    api.begin_qc_test(ster["id"], QA)
    api.record_qc_test(ster["id"], record_qc_payload(pass_flag=False), QA)
    # Investigation clears the lot back to AVAILABLE.
    api.release_quarantine_lot(lot["id"], QA)

    batch2 = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    charge_usage(batch2["id"], lot["id"], grams_used=10)
    started = validate_success(api.start_batch(batch2["id"], COMP), 200)
    assert started["status"] == "IN_PROCESS"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/dispense_blocked_by_prescription_not_active_pair_prep_prescription
# ─────────────────────────────────────────────────────────────────────────────

def test_dispense_blocked_by_cancelled_prescription(api):
    """PRD §3.9: "a 503A PRESCRIPTION unit requires an active same-formula
    prescription_id and forbids an office_account_name ... A channel mismatch is
    rejected with ERR_DISPENSE_CHANNEL_MISMATCH."

    Design: Difficulty/cross_entity_state_dependency/dispense_blocked_by_prescription_not_active_pair_prep_prescription
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Hydroxyzine 10mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    build_rx = create_prescription(facility["id"], mfr["id"], patient_name="Build Rx",
                                   units_prescribed=5)
    cancel_rx = create_prescription(facility["id"], mfr["id"], patient_name="Cancel Rx",
                                    units_prescribed=5)
    api.cancel_prescription(cancel_rx["id"], DISP)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": build_rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]

    res = api.create_dispense(
        create_dispense_payload(facility["id"], prep["id"], prescription_id=cancel_rx["id"]),
        DISP)
    validate_error(res, "ERR_DISPENSE_CHANNEL_MISMATCH", expected_status=422)
    after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert after["dispense_status"] == "IN_INVENTORY"


def test_dispense_against_active_prescription_succeeds(api):
    """PRD §3.9: "a 503A PRESCRIPTION unit requires an active same-formula
    prescription_id and forbids an office_account_name". PRD §3.9: "A successful
    dispense creates a Dispense record, moves the unit's dispense_status from
    IN_INVENTORY to DISPENSED".

    Design: Difficulty/cross_entity_state_dependency/dispense_blocked_by_prescription_not_active_pair_prep_prescription
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Hydroxyzine 10mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Build Rx",
                             units_prescribed=5)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]

    # Same prescription (ACTIVE) → the prep-prescription pairing coheres.
    validate_success(
        api.create_dispense(
            create_dispense_payload(facility["id"], prep["id"], prescription_id=rx["id"]),
            DISP), 201)
    after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert after["dispense_status"] == "DISPENSED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/beyond_use_date_boundary_dispense_inclusive_window
# ─────────────────────────────────────────────────────────────────────────────

def test_dispense_one_second_past_beyond_use_rejected(api):
    """PRD §3.9: "the facility's current_utc must be at or before the unit's
    beyond_use_utc, or the dispense is rejected with ERR_BEYOND_USE_DATE_PASSED."

    Design: Difficulty/resource_temporal_overlap/beyond_use_date_boundary_dispense_inclusive_window
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Ibuprofen 100mg/mL Susp",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=14,
                     theoretical_yield_units=5, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Morgan Bly",
                             units_prescribed=5)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]
    assert prep["beyond_use_utc"] == "2026-06-15T00:00:00.000Z"
    # One second past the BUD.
    api.set_clock(facility["id"], set_clock_payload("2026-06-15T00:00:01.000Z"), ADMIN)

    res = api.create_dispense(
        create_dispense_payload(facility["id"], prep["id"], prescription_id=rx["id"]), DISP)
    validate_error(res, "ERR_BEYOND_USE_DATE_PASSED", expected_status=409)
    after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert after["dispense_status"] == "IN_INVENTORY"


def test_dispense_exactly_at_beyond_use_date_succeeds(api):
    """PRD §3.9: "the facility's current_utc must be at or before the unit's
    beyond_use_utc, or the dispense is rejected with ERR_BEYOND_USE_DATE_PASSED."

    Design: Difficulty/resource_temporal_overlap/beyond_use_date_boundary_dispense_inclusive_window
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Ibuprofen 100mg/mL Susp",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=14,
                     theoretical_yield_units=5, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Morgan Bly",
                             units_prescribed=5)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]
    assert prep["beyond_use_utc"] == "2026-06-15T00:00:00.000Z"
    # current_utc set exactly TO the beyond_use_utc (inclusive right edge).
    api.set_clock(facility["id"], set_clock_payload("2026-06-15T00:00:00.000Z"), ADMIN)

    validate_success(
        api.create_dispense(
            create_dispense_payload(facility["id"], prep["id"], prescription_id=rx["id"]),
            DISP), 201)
    after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert after["dispense_status"] == "DISPENSED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/create_batch_referenced_mfr_not_found
# ─────────────────────────────────────────────────────────────────────────────

def test_create_batch_with_nonexistent_mfr(api):
    """PRD §3.11: "for create operations that carry foreign keys in the body ...
    each referenced resource must exist within the same facility, or the create is
    rejected with ERR_REFERENCED_RESOURCE_NOT_FOUND."

    Design: Corner/validations/create_batch_referenced_mfr_not_found
    """
    facility = create_facility("503B", clock=None)
    res = api.create_batch(
        {"facility_id": facility["id"],
         "master_formulation_record_id": "00000000-0000-4000-8000-000000000000",
         "purpose": "OFFICE_USE"}, COMP)
    validate_error(res, "ERR_REFERENCED_RESOURCE_NOT_FOUND", expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/create_office_use_batch_at_503a_facility_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_office_use_batch_at_503a_rejected(api):
    """PRD §3.6: "a 503A facility may never create an OFFICE_USE batch, and
    OFFICE_USE is permitted only at a 503B facility. Any violation of this
    purpose/prescription coherence is rejected with
    ERR_PURPOSE_PRESCRIPTION_MISMATCH."

    Design: Corner/validations/create_office_use_batch_at_503a_facility_rejected
    """
    facility = create_facility("503A", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    res = api.create_batch(
        create_batch_payload(facility["id"], mfr["id"], "OFFICE_USE"), COMP)
    validate_error(res, "ERR_PURPOSE_PRESCRIPTION_MISMATCH", expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/create_prescription_batch_without_prescription_id_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_prescription_batch_without_prescription_id_rejected(api):
    """PRD §3.6: "a PRESCRIPTION batch requires a prescription_id whose prescription
    belongs to the same formula and facility ... Any violation of this
    purpose/prescription coherence is rejected with
    ERR_PURPOSE_PRESCRIPTION_MISMATCH."

    Design: Corner/validations/create_prescription_batch_without_prescription_id_rejected
    """
    facility = create_facility("503A", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    res = api.create_batch(
        create_batch_payload(facility["id"], mfr["id"], "PRESCRIPTION"), COMP)
    validate_error(res, "ERR_PURPOSE_PRESCRIPTION_MISMATCH", expected_status=422)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/start_blocked_lot_insufficient_grams
# ─────────────────────────────────────────────────────────────────────────────

def test_start_blocked_by_insufficient_lot_grams(api):
    """PRD §3.6: "And every charged lot's remaining_grams must be at least the
    grams_used charged against it at that point, or the start is rejected with
    ERR_LOT_INSUFFICIENT_GRAMS."

    Design: Corner/validations/start_blocked_lot_insufficient_grams
    """
    facility = create_facility("503B", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=5,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")
    charge_usage(batch["id"], lot["id"], grams_used=10)

    res = api.start_batch(batch["id"], COMP)
    validate_error(res, "ERR_LOT_INSUFFICIENT_GRAMS", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], COMP), 200)
    assert after["status"] == "DRAFT"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/dispense_office_use_unit_with_prescription_id_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_dispense_office_use_unit_with_prescription_id_rejected(api):
    """PRD §3.9: "a 503B OFFICE_USE unit requires an office_account_name (the
    receiving clinic or office name) and forbids a prescription_id. A channel
    mismatch is rejected with ERR_DISPENSE_CHANNEL_MISMATCH."

    Design: Corner/validations/dispense_office_use_unit_with_prescription_id_rejected
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    stray_rx = create_prescription(facility["id"], mfr["id"], patient_name="Stray Rx",
                                   units_prescribed=5)
    batch = create_released_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="OFFICE_USE")
    prep = list_finished_preparations(batch["id"])[0]

    res = api.create_dispense(
        create_dispense_payload(facility["id"], prep["id"], prescription_id=stray_rx["id"]),
        DISP)
    validate_error(res, "ERR_DISPENSE_CHANNEL_MISMATCH", expected_status=422)
    after = validate_success(api.get_finished_preparation(prep["id"], DISP), 200)
    assert after["dispense_status"] == "IN_INVENTORY"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/dispense_unit_not_released_when_awaiting_qc
# ─────────────────────────────────────────────────────────────────────────────

def test_dispense_unit_not_released_when_awaiting_qc(api):
    """PRD §3.9: "the unit's qc_status must be QC_RELEASED, or the dispense is
    rejected with ERR_UNIT_NOT_RELEASED."

    Design: Corner/validations/dispense_unit_not_released_when_awaiting_qc
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=5)
    # Compiled but NOT released → preps AWAITING_QC.
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 5, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    prep = list_finished_preparations(batch["id"])[0]

    res = api.create_dispense(
        create_dispense_payload(facility["id"], prep["id"], prescription_id=rx["id"]), DISP)
    validate_error(res, "ERR_UNIT_NOT_RELEASED", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/errors/err_qc_not_in_state_record_before_begin
# ─────────────────────────────────────────────────────────────────────────────

def test_record_qc_before_begin_rejected(api):
    """PRD §3.7: "The pharmacist then records the result on an IN_PROGRESS test
    (otherwise ERR_QC_NOT_IN_STATE)".

    Design: Corner/errors/err_qc_not_in_state_record_before_begin
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
    qc = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "POTENCY_ASSAY",
                               measured_value=100, lower_limit=90, upper_limit=110), QA))

    # record without begin → still PENDING
    res = api.record_qc_test(qc["id"], record_qc_payload(measured_value=100), QA)
    validate_error(res, "ERR_QC_NOT_IN_STATE", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/errors/err_invalid_request_negative_grams_used
# ─────────────────────────────────────────────────────────────────────────────

def test_charge_negative_grams_rejected(api):
    """PRD §3.11: "Malformed bodies, missing required fields, type mismatches, and
    out-of-range numerics (such as a negative grams_used or an actual_yield_units
    below zero) are rejected with ERR_INVALID_REQUEST".

    Design: Corner/errors/err_invalid_request_negative_grams_used
    """
    facility = create_facility("503B", clock=None)
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")

    res = api.create_batch_ingredient_usage(
        {"compounding_batch_id": batch["id"], "ingredient_lot_id": lot["id"],
         "grams_used": -5}, COMP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
