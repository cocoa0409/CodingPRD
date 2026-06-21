"""Dose-validity age boundary, completeness/up-to-date variant, and the
precaution-vs-contraindication input filter."""
from test_helpers import (
    validate_success, get_success_data, setup_catalog_and_patient,
    setup_patient_with_doses, run_evaluation, create_allergy, record_dose,
    api_client, make_registrar_headers, create_product_payload,
)

REG = make_registrar_headers()

DTAP = dict(product_code="DTAP", antigen="DTAP", doses_in_series=5,
            min_age_days=42, recommended_age_days=60, min_interval_days=28,
            grace_period_days=4)
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0)


def test_dose_below_min_age_is_invalid_age(api):
    """PRD §2.7: "if the patient's age in days is strictly less than the
    product's min_age_days reduced by the grace window, its validity is
    INVALID_AGE and it is not counted".

    A DTAP dose at age 37 days (< min_age 42 - grace 4 = 38) is INVALID_AGE.

    Design: Corner/calculations/dose_below_min_age_is_invalid_age
    """
    _, _, _, _, doses = setup_patient_with_doses(
        dose_dates=["2025-02-07"],
        product_overrides=create_product_payload(**DTAP),
        patient_overrides={"date_of_birth": "2025-01-01"})
    assert doses[0]["validity"] == "INVALID_AGE", \
        f"expected INVALID_AGE at age 37, got {doses[0]['validity']}"


def test_dose_at_exactly_min_age_minus_grace_is_valid(api):
    """PRD §2.7: "the standard grace window is four days, applied identically to
    both the minimum-age and the minimum-interval thresholds ... otherwise the
    dose is VALID, the valid-dose index advances by one, this dose's dose_number
    is set to that new index".

    A DTAP dose at age exactly 38 days (min_age 42 - grace 4) is VALID with
    dose_number 1.

    Design: Corner/calculations/dose_exactly_at_min_age_minus_grace_is_valid
    """
    _, _, _, _, doses = setup_patient_with_doses(
        dose_dates=["2025-02-08"],
        product_overrides=create_product_payload(**DTAP),
        patient_overrides={"date_of_birth": "2025-01-01"})
    assert doses[0]["validity"] == "VALID", \
        f"expected VALID at age 38, got {doses[0]['validity']}"
    assert doses[0]["dose_number"] == 1


def test_completeness_100_when_all_satisfied_up_to_date(api):
    """PRD §3.6: "if every antigen is satisfied, the status is UP_TO_DATE".
    PRD §3.6: "a satisfied flag that is true exactly when the valid-dose count is
    greater than or equal to the required count."

    A single fully satisfied mandated antigen yields completeness_pct 100.00 and
    overall_status UP_TO_DATE.

    Design: Corner/calculations/completeness_100_when_all_satisfied_up_to_date
    """
    _, _, _, patient, _ = setup_patient_with_doses(
        dose_dates=["2025-01-01"],
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    ev = run_evaluation(patient["id"], "2026-06-01")
    assert ev["completeness_pct"] == 100.00, f"got {ev['completeness_pct']}"
    assert ev["overall_status"] == "UP_TO_DATE", f"got {ev['overall_status']}"


def test_precaution_allergy_does_not_block_dose(api):
    """PRD §3.4: "A CONTRAINDICATED record blocks any new dose of a product
    mapping to that antigen for as long as the record stands; a PRECAUTION record
    allows the dose while standing as a recorded warning."

    A PRECAUTION allergy for the antigen does not block recording; the dose
    succeeds with validity VALID.

    Design: Corner/calculations/precaution_allergy_does_not_block_dose
    """
    product, provider, lot, patient = setup_catalog_and_patient(
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    create_allergy(patient["id"], "C1", severity="PRECAUTION")
    dose = record_dose(patient["id"], lot["id"], provider["id"], "2025-01-01")
    assert dose["validity"] == "VALID", f"got {dose['validity']}"
