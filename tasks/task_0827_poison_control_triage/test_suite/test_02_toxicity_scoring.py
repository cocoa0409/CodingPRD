"""Exposure toxicity scoring: route bioavailability, band boundaries, and the
substance foreign-key reference checks.

Translations of Difficulty rule `combinatorial_formula` / `boundary_precision_check`
and Corner `validations` / `endpoints` instances.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_exposure,
    make_specialist_headers,
    open_case,
    seed_specialist,
    seed_substance,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ingestion_route_full_bioavailability(api):
    """PRD §3.3: "a bioavailability factor is selected by route: `INGESTION` and
    `INJECTION` are 1.0, `INHALATION` is 0.8, `DERMAL` is 0.4, and `OCULAR` is 0.3."

    Design: Difficulty/combinatorial_formula/toxicity_route_branch_nonlinear
    """
    substance = seed_substance(api)  # tdk 150, onset 4
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20, chief_complaint="mixed route")
    exp = add_exposure(api, case["id"], spi["id"], substance["id"], route="INGESTION",
                       dose_range_low_mg=3000, dose_range_high_mg=3000)
    assert exp["toxicity_score"] == 1.00


def test_dermal_route_reduced_bioavailability(api):
    """PRD §3.3: "a bioavailability factor is selected by route: `INGESTION` and
    `INJECTION` are 1.0, `INHALATION` is 0.8, `DERMAL` is 0.4, and `OCULAR` is 0.3."
    PRD §3.3: "Its `severity_band` is `MINIMAL` when the score is below 0.25,
    `MODERATE` when it is at least 0.25 but below 0.75, `SEVERE` when it is at least
    0.75 but below 1.5, and `CRITICAL` when it is 1.5 or greater."

    Design: Difficulty/combinatorial_formula/toxicity_route_branch_nonlinear
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20, chief_complaint="mixed route")
    exp = add_exposure(api, case["id"], spi["id"], substance["id"], route="DERMAL",
                       dose_range_low_mg=3000, dose_range_high_mg=3000)
    assert exp["toxicity_score"] == 0.40
    assert exp["severity_band"] == "MODERATE"


def test_toxicity_score_at_exact_severe_boundary(api):
    """PRD §3.3: "The `toxicity_score` is the dose ratio multiplied by the time
    factor, rounded half-up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/severity_band_at_exact_0_75_is_severe
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20)
    exp = add_exposure(api, case["id"], spi["id"], substance["id"], route="INGESTION",
                       dose_range_low_mg=2250, dose_range_high_mg=2250)
    assert exp["toxicity_score"] == 0.75


def test_severity_band_075_is_severe_inclusive(api):
    """PRD §3.3: "Its `severity_band` is `MINIMAL` when the score is below 0.25,
    `MODERATE` when it is at least 0.25 but below 0.75, `SEVERE` when it is at least
    0.75 but below 1.5, and `CRITICAL` when it is 1.5 or greater."

    Design: Difficulty/boundary_precision_check/severity_band_at_exact_0_75_is_severe
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20)
    exp = add_exposure(api, case["id"], spi["id"], substance["id"], route="INGESTION",
                       dose_range_low_mg=2250, dose_range_high_mg=2250)
    assert exp["toxicity_score"] == 0.75
    assert exp["severity_band"] == "SEVERE"


def test_exposure_with_unknown_substance_rejected(api):
    """PRD §2.8: "Separately, when a request body references a configuration or peer
    resource by foreign key — a `substance_id`, `facility_id`, `risk_assessment_id`,
    or `primary_substance_id` — and that reference does not resolve, the request
    fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/reference_not_found_bad_substance
    """
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    resp = api.create_exposure(
        case["id"],
        {"substance_id": NON_EXISTENT_UUID, "route": "INGESTION",
         "dose_range_low_mg": 100, "dose_range_high_mg": 200, "time_since_exposure_hours": 1},
        make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_exposures_reverse_list_by_substance(api):
    """PRD §3.3: "Exposures may be listed and filtered by `case_id` or by
    `substance_id`."

    Design: Corner/endpoints/exposures_reverse_list_by_substance
    """
    substance = seed_substance(api)
    spi = seed_specialist(api)
    headers = make_specialist_headers(spi["id"])
    case1 = open_case(api, spi["id"], chief_complaint="c1")
    add_exposure(api, case1["id"], spi["id"], substance["id"],
                 dose_range_low_mg=100, dose_range_high_mg=200, time_since_exposure_hours=1)
    case2 = open_case(api, spi["id"], patient_age_years=7, patient_weight_kg=22,
                      patient_sex="FEMALE", chief_complaint="c2")
    add_exposure(api, case2["id"], spi["id"], substance["id"],
                 dose_range_low_mg=300, dose_range_high_mg=400, time_since_exposure_hours=1)
    _, meta = validate_paginated(api.list_exposures(headers, params={"substance_id": substance["id"]}))
    assert meta["total_count"] == 2
