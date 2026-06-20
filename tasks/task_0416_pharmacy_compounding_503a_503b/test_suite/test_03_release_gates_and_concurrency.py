"""Batch-release gates, segregation of duties, validation priority, and OCC.

The release transition is the most heavily guarded in the system. These tests
exercise its fixed-order checks (state → OCC → segregation → QC → environmental →
anticipatory), the priority resolution when several gates fail at once, and the
optimistic-concurrency contract on expected_batch_version.
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
    quarantine_batch,
    add_passing_required_qc,
    create_qc_test_payload,
    record_qc_payload,
    compile_payload,
    release_payload,
    create_environmental_log_payload,
)

COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]


def _quarantined_503a_batch(api, *, yield_units=100, anticipatory_max_units=500,
                            with_qc=True, compiler_id="comp-user-1", name="F1",
                            dosage_form="ORAL_SOLID"):
    """Helper: 503A PRESCRIPTION batch driven to QUARANTINED. Returns (batch, version)."""
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name=name, dosage_form=dosage_form,
                     default_bud_days_nonsterile=90, theoretical_yield_units=yield_units,
                     anticipatory_max_units=anticipatory_max_units)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=yield_units)
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], yield_units, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]}, compiler_id=compiler_id)
    if with_qc:
        add_passing_required_qc(batch["id"], is_sterile=False)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], QA))
    return batch, cur["version"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/release_state_precondition_beats_segregation_safety
# ─────────────────────────────────────────────────────────────────────────────

def test_release_state_check_beats_segregation(api):
    """PRD §3.8: "First, the batch must be QUARANTINED, or the release is rejected
    with ERR_BATCH_NOT_IN_STATE." and "Then segregation of duties: the releasing
    operator's X-User-ID must differ from the batch's compiled_by_user_id, or the
    release is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/release_state_precondition_beats_segregation_safety
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Estradiol 0.5mg Cap", dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=50)
    # Compiled but NOT quarantined → still COMPILED; releaser == compiler.
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]}, compiler_id="comp-user-1")
    cur = get_success_data(api.get_batch(batch["id"], QA))

    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_qa_headers("comp-user-1"))
    validate_error(res, "ERR_BATCH_NOT_IN_STATE", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "COMPILED"


def test_segregation_fires_alone_once_state_precondition_passes(api):
    """PRD §3.8: "Then segregation of duties: the releasing operator's X-User-ID
    must differ from the batch's compiled_by_user_id, or the release is rejected
    with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/priority_pair_validation_conflict/release_state_precondition_beats_segregation_safety
    """
    # State precondition now SATISFIED (batch QUARANTINED), only segregation wrong:
    # the lower-priority error surfaces in isolation, confirming the precedence.
    batch, version = _quarantined_503a_batch(api, yield_units=100, compiler_id="comp-user-1")
    res = api.release_batch(batch["id"], release_payload(version),
                            make_qa_headers("comp-user-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/release_segregation_safety_beats_anticipatory_fiscal
# ─────────────────────────────────────────────────────────────────────────────

def test_release_segregation_beats_anticipatory_cap(api):
    """PRD §3.8: "Then segregation of duties: the releasing operator's X-User-ID
    must differ from the batch's compiled_by_user_id, or the release is rejected
    with ERR_SEGREGATION_OF_DUTIES." and "Finally, for an OFFICE_USE batch only,
    the anticipatory gate: the formula's anticipatory ledger remaining_units must
    be at least the batch's actual_yield_units, or the release is rejected with
    ERR_ANTICIPATORY_LIMIT_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/release_segregation_safety_beats_anticipatory_fiscal
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Diclofenac 1% Gel", dosage_form="TOPICAL",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=1)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE",
        compiler_id="comp-user-1")
    add_passing_required_qc(batch["id"], is_sterile=False)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], QA))

    # releaser == compiler (segregation) AND yield 100 > remaining 1 (anticipatory)
    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_qa_headers("comp-user-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


def test_anticipatory_cap_fires_alone_once_segregation_passes(api):
    """PRD §3.8: "Finally, for an OFFICE_USE batch only, the anticipatory gate: the
    formula's anticipatory ledger remaining_units must be at least the batch's
    actual_yield_units, or the release is rejected with
    ERR_ANTICIPATORY_LIMIT_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/release_segregation_safety_beats_anticipatory_fiscal
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Diclofenac 1% Gel", dosage_form="TOPICAL",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=1)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_compiled_batch(
        facility["id"], mfr["id"], lot["id"], 100, purpose="OFFICE_USE",
        compiler_id="comp-user-1")
    add_passing_required_qc(batch["id"], is_sterile=False)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], QA))

    # Segregation now SATISFIED (distinct QA releaser); only anticipatory cap wrong.
    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_qa_headers("qa-user-2"))
    validate_error(res, "ERR_ANTICIPATORY_LIMIT_EXCEEDED", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/release_qc_incomplete_when_required_tests_missing
# ─────────────────────────────────────────────────────────────────────────────

def test_release_with_no_qc_tests_is_incomplete(api):
    """PRD §3.8: "every required QC test must exist and have result of PASSED, and
    none may be FAILED. The required set is always POTENCY_ASSAY and
    VISUAL_INSPECTION ... if any required test is missing or not yet passed the
    release is rejected with ERR_QC_INCOMPLETE".

    Design: Corner/validations/release_qc_incomplete_when_required_tests_missing
    """
    batch, version = _quarantined_503a_batch(api, yield_units=5, with_qc=False)
    res = api.release_batch(batch["id"], release_payload(version),
                            make_qa_headers("qa-user-2"))
    validate_error(res, "ERR_QC_INCOMPLETE", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/release_qc_failed_blocks_release
# ─────────────────────────────────────────────────────────────────────────────

def test_release_with_failed_qc_blocks_release(api):
    """PRD §3.8: "while any required test that is FAILED rejects the release with
    ERR_QC_FAILED."

    Design: Corner/validations/release_qc_failed_blocks_release
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
        batch_overrides={"prescription_id": rx["id"]}, compiler_id="comp-user-1")
    # POTENCY_ASSAY recorded FAILED (80 < 90)
    pot = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "POTENCY_ASSAY",
                               measured_value=80, lower_limit=90, upper_limit=110), QA))
    api.begin_qc_test(pot["id"], QA)
    failed = validate_success(
        api.record_qc_test(pot["id"], record_qc_payload(measured_value=80), QA), 200)
    assert failed["result"] == "FAILED"
    vis = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "VISUAL_INSPECTION"), QA))
    api.begin_qc_test(vis["id"], QA)
    api.record_qc_test(vis["id"], record_qc_payload(pass_flag=True), QA)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], QA))

    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_qa_headers("qa-user-2"))
    validate_error(res, "ERR_QC_FAILED", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/validations/release_environmental_excursion_blocks_sterile_release
# ─────────────────────────────────────────────────────────────────────────────

def test_release_blocked_by_environmental_excursion(api):
    """PRD §3.8: "Then, for sterile batches only, the environmental gate: there must
    be no USP_797 environmental log with in_spec false whose reading_utc falls
    within the window from the batch's start through the present; such an excursion
    rejects the release with ERR_ENVIRONMENTAL_EXCURSION."

    Design: Corner/validations/release_environmental_excursion_blocks_sterile_release
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Sterile F", dosage_form="STERILE_AQUEOUS",
                     default_bud_days_nonsterile=1, theoretical_yield_units=5,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], labeled_potency_pct=99.4, initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")
    # Out-of-spec USP_797 reading logged in the batch window (10 > limit 5).
    api.create_environmental_log(
        create_environmental_log_payload(
            facility["id"], usp_chapter="USP_797", reading_type="VIABLE_AIR_CFU",
            measured_value=10, action_limit=5), QA)
    api.compile_batch(batch["id"], compile_payload(5), make_compounding_headers("comp-user-1"))
    # Endotoxin projection = measured * 1000 * potency_adjusted_grams / yield.
    # potency_adjusted_grams = 10 * 99.4/100 = 9.94 → total active mg = 9940.
    # With yield 5 and STERILE_AQUEOUS ceiling 175 EU/unit, measured must be
    # <= 175*5/9940 ≈ 0.088 to PASS; use 0.01 so QC clears and the environmental
    # gate (checked after QC) is the blocker under test.
    add_passing_required_qc(batch["id"], is_sterile=True, endotoxin_measured_value=0.01)
    quarantine_batch(batch["id"])
    cur = get_success_data(api.get_batch(batch["id"], QA))

    res = api.release_batch(batch["id"], release_payload(cur["version"]),
                            make_qa_headers("qa-user-2"))
    validate_error(res, "ERR_ENVIRONMENTAL_EXCURSION", expected_status=409)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/occ_release_correct_version_succeeds
# ─────────────────────────────────────────────────────────────────────────────

def test_release_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.8: "increments the batch's version by one" (on release) and PRD §2.7:
    "the server compares expected_batch_version against the batch's current
    version."

    Design: Corner/cross_cutting_complexity_layers/occ_release_correct_version_succeeds
    """
    batch, version = _quarantined_503a_batch(api, yield_units=5)
    released = validate_success(
        api.release_batch(batch["id"], release_payload(version),
                          make_qa_headers("qa-user-2")), 200)
    assert released["status"] == "RELEASED"
    assert released["version"] == version + 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/occ_release_stale_version_rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_release_with_stale_version_rejected(api):
    """PRD §2.7: "If they do not match — meaning a prior release has already
    advanced the batch's version since the client last read it — the release is
    rejected with ERR_STALE_VERSION and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_release_stale_version_rejected
    """
    batch, version = _quarantined_503a_batch(api, yield_units=5)
    res = api.release_batch(batch["id"], release_payload(version - 1),
                            make_qa_headers("qa-user-2"))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_batch(batch["id"], QA), 200)
    assert after["status"] == "QUARANTINED"
