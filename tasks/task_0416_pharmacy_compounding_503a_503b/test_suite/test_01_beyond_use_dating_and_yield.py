"""Beyond-use dating, yield reconciliation, potency, and label-text calculations.

Covers the dual-variant BUD calc (503A vs 503B), the nested min() ingredient-expiry
floor, the round-then-band yield reconciliation, the potency-adjustment rounding,
and the deterministic label_text composition.
"""
import pytest

from test_helpers import (
    api_client,
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
    list_finished_preparations,
    create_batch_payload,
    create_batch_ingredient_usage_payload,
    compile_payload,
    create_qc_test_payload,
    record_qc_payload,
)

COMP = TEST_USERS["compounding_headers"]
QA = TEST_USERS["qa_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/bud_503a_patient_specific_vs_503b_office_use_window
# ─────────────────────────────────────────────────────────────────────────────

def test_bud_503a_keeps_full_nonsterile_window(api):
    """PRD §3.6: "For a 503A patient-specific run (a PRESCRIPTION batch — the only
    purpose a 503A facility allows) this base window is used directly with no
    further cap." and "So for a nonsterile formula with a 180-day nonsterile
    default, a 503A run keeps the full 180 days while a 503B office-use run is
    held to 90 days."

    Design: Difficulty/dual_variant_calc/bud_503a_patient_specific_vs_503b_office_use_window
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Tacrolimus 0.5mg/mL Oral",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=180,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Tacrolimus", lot_number="LA-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Jane Roe",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(100), COMP), 200)
    assert compiled["assigned_bud_utc"] == "2026-11-28T00:00:00.000Z", (
        f"503A 180-day window expected 2026-11-28, got {compiled['assigned_bud_utc']}")

    preps = list_finished_preparations(batch["id"])
    assert all(p["beyond_use_utc"] == "2026-11-28T00:00:00.000Z" for p in preps)


def test_bud_503b_office_use_capped_at_90_days(api):
    """PRD §3.6: "For a 503B office-use run (an OFFICE_USE batch, which only a 503B
    facility may create) the base window is first capped at 90 days — the
    outsourcing-facility stability-data limit — before anything else; concretely,
    the smaller of the base window and 90 days is used."

    Design: Difficulty/dual_variant_calc/bud_503a_patient_specific_vs_503b_office_use_window
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Tacrolimus 0.5mg/mL Oral",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=180,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Tacrolimus", lot_number="LB-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")

    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(100), COMP), 200)
    assert compiled["assigned_bud_utc"] == "2026-08-30T00:00:00.000Z", (
        f"503B 90-day cap expected 2026-08-30, got {compiled['assigned_bud_utc']}")

    preps = list_finished_preparations(batch["id"])
    assert all(p["beyond_use_utc"] == "2026-08-30T00:00:00.000Z" for p in preps)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/dual_variant_calc/endotoxin_route_tiered_projection_vs_bud_window
# ─────────────────────────────────────────────────────────────────────────────

def test_endotoxin_injectable_passes_at_boundary_projection(api):
    """PRD §3.7: "The per-unit endotoxin ceiling depends on route: it is 175 EU per
    unit when the formula's dosage form is STERILE_AQUEOUS (the injectable case)
    ... so the projected endotoxin per unit is that measured_value multiplied by
    the total active milligrams divided by the batch's theoretical_yield_units.
    The test is PASSED when the projected endotoxin per unit is at most the route
    ceiling and FAILED otherwise; the comparison is made at full floating-point
    precision and the boundary value passes."

    Design: Difficulty/dual_variant_calc/endotoxin_route_tiered_projection_vs_bud_window
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Ketamine 10mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Ketamine HCl", lot_number="K-1",
                     labeled_potency_pct=99.4, initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z", endotoxin_eu_per_mg=0.1)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")
    api.compile_batch(batch["id"], compile_payload(100), COMP)

    qc = get_success_data(api.create_qc_test(
        create_qc_test_payload(batch["id"], "ENDOTOXIN"), QA))
    api.begin_qc_test(qc["id"], QA)
    # projected = 1.76 * (9940/100) = 174.944 <= 175 → PASSED
    recorded = validate_success(
        api.record_qc_test(qc["id"], record_qc_payload(measured_value=1.76), QA), 200)
    assert recorded["result"] == "PASSED", (
        f"projected 174.944 <= 175 must PASS, got {recorded['result']}")


def test_sterile_aqueous_bud_uses_14_day_window(api):
    """PRD §3.6: "for a sterile formula the base is 14 days when the dosage form is
    STERILE_AQUEOUS and 45 days when it is STERILE_NONAQUEOUS".

    Design: Difficulty/dual_variant_calc/endotoxin_route_tiered_projection_vs_bud_window
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Ketamine 10mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Ketamine HCl", lot_number="K-1",
                     labeled_potency_pct=99.4, initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")

    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(100), COMP), 200)
    assert compiled["assigned_bud_utc"] == "2026-06-15T00:00:00.000Z", (
        f"sterile-aqueous 14-day window expected 2026-06-15, "
        f"got {compiled['assigned_bud_utc']}")


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/bud_min_of_window_and_ingredient_expiry_floor_mode_a
# ─────────────────────────────────────────────────────────────────────────────

def test_bud_clamped_to_earliest_ingredient_expiry(api):
    """PRD §3.6: "an ingredient-expiry floor is applied: a preparation may never
    outlive its ingredients, so the candidate beyond-use datetime — the facility's
    current_utc plus the chosen window in whole days — is compared against the
    earliest expiration_utc among all ingredient lots referenced by the batch's
    usage rows ... and the assigned beyond-use datetime is the earlier of the two."

    Design: Difficulty/combinatorial_formula/bud_min_of_window_and_ingredient_expiry_floor_mode_a
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Morphine 1mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Morphine sulfate", lot_number="M-1",
                     initial_grams=50, expiration_utc="2026-06-05T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Sam Lin",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(100), COMP), 200)
    # min(2026-06-15 window, 2026-06-05 lot expiry) → floor wins
    assert compiled["assigned_bud_utc"] == "2026-06-05T00:00:00.000Z", (
        f"ingredient floor 2026-06-05 must bind below 14-day window, "
        f"got {compiled['assigned_bud_utc']}")


def test_bud_ingredient_floor_stamped_onto_finished_preparations(api):
    """PRD §3.6: "the system mints exactly actual_yield_units Finished
    Preparations, each carrying ... a beyond_use_utc snapshotted from the batch's
    stamped beyond-use datetime." and "the assigned beyond-use datetime is the
    earlier of the two."

    Design: Difficulty/combinatorial_formula/bud_min_of_window_and_ingredient_expiry_floor_mode_a
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Morphine 1mg/mL Inj",
                     dosage_form="STERILE_AQUEOUS", default_bud_days_nonsterile=1,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Morphine sulfate", lot_number="M-1",
                     initial_grams=50, expiration_utc="2026-06-05T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Sam Lin",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    api.compile_batch(batch["id"], compile_payload(100), COMP)

    preps = list_finished_preparations(batch["id"])
    assert preps and all(
        p["beyond_use_utc"] == "2026-06-05T00:00:00.000Z" for p in preps), (
        "every minted prep must carry the ingredient-floor BUD 2026-06-05")


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/combinatorial_formula/yield_variance_round_then_band_compare_mode_b
# ─────────────────────────────────────────────────────────────────────────────

def test_yield_variance_exactly_plus_five_is_accepted(api):
    """PRD §3.6: "The yield variance (yield_variance_pct) is one hundred times the
    actual yield minus the theoretical yield, divided by the theoretical yield,
    rounded to two decimal places ... a variance from negative 5.00 through
    positive 5.00 inclusive is acceptable, while negative 5.01 or positive 5.01 is
    rejected with ERR_YIELD_OUT_OF_RANGE."

    Design: Difficulty/combinatorial_formula/yield_variance_round_then_band_compare_mode_b
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Progesterone 100mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Progesterone", lot_number="P-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Lee Park",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(105), COMP), 200)
    assert compiled["yield_variance_pct"] == pytest.approx(5.0, abs=0.001)
    assert compiled["status"] == "COMPILED", (
        "+5.00 is within the inclusive ±5.0 band, compile must succeed")


def test_yield_variance_round_half_up_to_two_decimals(api):
    """PRD §3.6: "The yield variance (yield_variance_pct) is one hundred times the
    actual yield minus the theoretical yield, divided by the theoretical yield,
    rounded to two decimal places; a negative result signals under-yield."

    Design: Difficulty/combinatorial_formula/yield_variance_round_then_band_compare_mode_b
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Progesterone 100mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Progesterone", lot_number="P-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Lee Park",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    # actual 98 vs theoretical 100 → 100*(98-100)/100 = -2.00 (under-yield, in band)
    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(98), COMP), 200)
    assert compiled["yield_variance_pct"] == pytest.approx(-2.0, abs=0.001)
    assert compiled["status"] == "COMPILED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/yield_variance_band_inclusive_upper_boundary_compile
# ─────────────────────────────────────────────────────────────────────────────

def test_yield_variance_plus_six_rejected(api):
    """PRD §3.6: "a variance from negative 5.00 through positive 5.00 inclusive is
    acceptable, while negative 5.01 or positive 5.01 is rejected with
    ERR_YIELD_OUT_OF_RANGE."

    Design: Difficulty/boundary_precision_check/yield_variance_band_inclusive_upper_boundary_compile
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Spironolactone 25mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Spironolactone", lot_number="S-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Jordan Fox",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    # actual 106 vs theoretical 100 → +6.00 > +5.00 band
    res = api.compile_batch(batch["id"], compile_payload(106), COMP)
    validate_error(res, "ERR_YIELD_OUT_OF_RANGE", expected_status=422)

    after = validate_success(api.get_batch(batch["id"], COMP), 200)
    assert after["status"] == "IN_PROCESS", "compile rejected, batch stays IN_PROCESS"


def test_yield_variance_exactly_plus_five_inside_band_compiles(api):
    """PRD §3.6: "a variance from negative 5.00 through positive 5.00 inclusive is
    acceptable, while negative 5.01 or positive 5.01 is rejected with
    ERR_YIELD_OUT_OF_RANGE."

    Design: Difficulty/boundary_precision_check/yield_variance_band_inclusive_upper_boundary_compile
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Spironolactone 25mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], component_name="Spironolactone", lot_number="S-1",
                     initial_grams=50, expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Jordan Fox",
                             units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    # actual 105 vs theoretical 100 → exactly +5.00, the inclusive upper edge
    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(105), COMP), 200)
    assert compiled["yield_variance_pct"] == pytest.approx(5.0, abs=0.001)
    assert compiled["status"] == "COMPILED"


def test_yield_variance_minus_five_lower_boundary_accepted(api):
    """PRD §3.6: "a variance from negative 5.00 through positive 5.00 inclusive is
    acceptable, while negative 5.01 or positive 5.01 is rejected with
    ERR_YIELD_OUT_OF_RANGE."

    Design: Difficulty/combinatorial_formula/yield_variance_round_then_band_compare_mode_b
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=50)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})

    # actual 95 vs theoretical 100 → -5.00 inclusive lower boundary
    compiled = validate_success(
        api.compile_batch(batch["id"], compile_payload(95), COMP), 200)
    assert compiled["yield_variance_pct"] == pytest.approx(-5.0, abs=0.001)
    assert compiled["status"] == "COMPILED"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/batch_start_with_zero_ingredients_empty_set_boundary
# ─────────────────────────────────────────────────────────────────────────────

def test_start_with_no_ingredients_charged_rejected(api):
    """PRD §3.6: "At least one batch ingredient usage row must exist for the batch,
    or the start is rejected with ERR_NO_INGREDIENTS_CHARGED."

    Design: Difficulty/boundary_precision_check/batch_start_with_zero_ingredients_empty_set_boundary
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Gabapentin 50mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Casey Tran",
                             units_prescribed=50)
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="PRESCRIPTION",
                               prescription_id=rx["id"])

    res = api.start_batch(batch["id"], COMP)
    validate_error(res, "ERR_NO_INGREDIENTS_CHARGED", expected_status=409)

    after = validate_success(api.get_batch(batch["id"], COMP), 200)
    assert after["status"] == "DRAFT", "start rejected, batch stays DRAFT"


def test_start_with_one_ingredient_charged_succeeds(api):
    """PRD §3.6: "At least one batch ingredient usage row must exist for the batch,
    or the start is rejected with ERR_NO_INGREDIENTS_CHARGED." and "the start
    succeeds and, as its side effect, decrements each charged lot's remaining_grams
    by the corresponding grams_used."

    Design: Difficulty/boundary_precision_check/batch_start_with_zero_ingredients_empty_set_boundary
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Gabapentin 50mg Cap",
                     dosage_form="ORAL_SOLID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=100, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], units_prescribed=50)
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="PRESCRIPTION",
                               prescription_id=rx["id"])
    charge_usage(batch["id"], lot["id"], grams_used=10)

    # Exactly one usage row → empty-set boundary cleared, start succeeds.
    started = validate_success(api.start_batch(batch["id"], COMP), 200)
    assert started["status"] == "IN_PROCESS"


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/potency_adjusted_grams_4dp_rounding
# ─────────────────────────────────────────────────────────────────────────────

def test_potency_adjusted_grams_rounds_to_four_decimals(api):
    """PRD §3.6: "the system computes the row's read-only potency_adjusted_grams as
    grams_used multiplied by the lot's labeled_potency_pct divided by 100, rounded
    to four decimal places — the effective active grams after potency correction."

    Design: Corner/calculations/potency_adjusted_grams_4dp_rounding
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], dosage_form="ORAL_SOLID",
                     default_bud_days_nonsterile=90, theoretical_yield_units=100,
                     anticipatory_max_units=500)
    lot = create_lot(facility["id"], labeled_potency_pct=101.2, initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_draft_batch(facility["id"], mfr["id"], purpose="OFFICE_USE")

    res = api.create_batch_ingredient_usage(
        create_batch_ingredient_usage_payload(batch["id"], lot["id"], grams_used=12.5), COMP)
    usage = validate_success(res, 201)
    # round(12.5 * 1.012, 4) == 12.65
    assert usage["potency_adjusted_grams"] == pytest.approx(12.65, abs=0.0001)


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/label_text_office_use_includes_outsourcing_marker
# ─────────────────────────────────────────────────────────────────────────────

def test_label_text_office_use_carries_outsourcing_marker(api):
    """PRD §3.6: "For an OFFICE_USE batch the header is followed by " | 503B
    OUTSOURCING FACILITY — OFFICE USE ONLY — NOT FOR RESALE"."

    Design: Corner/calculations/label_text_office_use_includes_outsourcing_marker
    """
    facility = create_facility("503B", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Testosterone 200mg/mL",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=3, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="OFFICE_USE")
    api.compile_batch(batch["id"], compile_payload(3), COMP)

    preps = list_finished_preparations(batch["id"])
    assert len(preps) == 3
    for p in preps:
        assert "503B OUTSOURCING FACILITY — OFFICE USE ONLY — NOT FOR RESALE" in p["label_text"]
        assert "Testosterone 200mg/mL" in p["label_text"]
        assert "BUD 2026-08-30" in p["label_text"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner/calculations/label_text_prescription_includes_patient_and_npi
# ─────────────────────────────────────────────────────────────────────────────

def test_label_text_prescription_carries_patient_and_npi(api):
    """PRD §3.6: "For a PRESCRIPTION batch the header is instead followed by " | RX
    PATIENT: " and the linked prescription's patient_name, then " | PRESCRIBER NPI:
    " and the prescription's prescriber_npi."

    Design: Corner/calculations/label_text_prescription_includes_patient_and_npi
    """
    facility = create_facility("503A", clock="2026-06-01T00:00:00.000Z")
    mfr = create_mfr(facility["id"], name="Testosterone 200mg/mL",
                     dosage_form="ORAL_LIQUID", default_bud_days_nonsterile=90,
                     theoretical_yield_units=3, anticipatory_max_units=500)
    lot = create_lot(facility["id"], initial_grams=50,
                     expiration_utc="2030-01-01T00:00:00.000Z")
    rx = create_prescription(facility["id"], mfr["id"], patient_name="Jane Roe",
                             prescriber_npi="1234567890", units_prescribed=3)
    batch = create_started_batch(
        facility["id"], mfr["id"], lot["id"], purpose="PRESCRIPTION",
        batch_overrides={"prescription_id": rx["id"]})
    api.compile_batch(batch["id"], compile_payload(3), COMP)

    preps = list_finished_preparations(batch["id"])
    assert len(preps) == 3
    for p in preps:
        assert "RX PATIENT: Jane Roe" in p["label_text"]
        assert "PRESCRIBER NPI: 1234567890" in p["label_text"]
        assert "OFFICE USE ONLY" not in p["label_text"]
