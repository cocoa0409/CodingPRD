"""Entity CRUD/defaults/listing, RBAC denial, PASRR clearance, and the five-star
quality program.

Covers difficulty rule: dual_variant_calc (five-star full vs missing baseline), plus
corner entity/listing/rbac/endpoint instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    fixtures,
    factories as f,
    build_user_headers,
)

ADMIN = TEST_USERS["administrator_headers"]
COORD = TEST_USERS["admissions_coordinator_headers"]
MDS = TEST_USERS["mds_coordinator_headers"]
THERAPIST = TEST_USERS["therapist_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


# =====================================================================
# Difficulty/dual_variant_calc/five_star_full_measures_vs_missing_baseline
# =====================================================================

def _seed_full_quality_measures(facility_id):
    rows = [
        ("FALLS_WITH_INJURY", 1, 200),
        ("PRESSURE_ULCER", 2, 200),
        ("ANTIPSYCHOTIC_USE", 10, 200),
        ("REHOSPITALIZATION", 20, 200),
    ]
    for code, num, den in rows:
        get_success_data(api_client.create_quality_measure(
            facility_id,
            f.create_quality_measure_payload(measure_code=code, numerator=num, denominator=den,
                                             reporting_period="2026Q1"), ADMIN))


def test_five_star_full_measures_rating_five():
    """PRD §3.1: "The quality-measure total is the sum of the measure points across the
    four measure codes, taking, for each code, only its latest reporting period ... The
    quality-measure star component, quality_measure_rating, is then assigned from the
    quality-measure total by these cut points: 5 stars when the total is at least 360".

    Design: Difficulty/dual_variant_calc/five_star_full_measures_vs_missing_baseline
    """
    facility = fixtures.create_facility(certified_bed_count=10, health_inspection_rating=4, staffing_rating=4)
    _seed_full_quality_measures(facility["id"])
    summary = validate_success(api_client.get_facility_star_summary(facility["id"], ADMIN))
    assert summary["quality_measure_rating"] == 5, (
        f"all four top-tier measures (total 400) -> 5 stars, got {summary['quality_measure_rating']}")


def test_five_star_missing_measures_use_baseline():
    """PRD §3.1: "any measure code for which the facility has no data point contributes
    a baseline of 50 points ... 3 stars when from 200 through 279".

    Design: Difficulty/dual_variant_calc/five_star_full_measures_vs_missing_baseline
    """
    facility = fixtures.create_facility(certified_bed_count=10, health_inspection_rating=4, staffing_rating=4)
    # Only FALLS_WITH_INJURY entered (100 points); three missing -> 3*50 baseline; total 250.
    get_success_data(api_client.create_quality_measure(
        facility["id"],
        f.create_quality_measure_payload(measure_code="FALLS_WITH_INJURY", numerator=1, denominator=200,
                                         reporting_period="2026Q1"), ADMIN))
    summary = validate_success(api_client.get_facility_star_summary(facility["id"], ADMIN))
    assert summary["quality_measure_rating"] == 3, (
        f"one measure (100) + three baselines (150) = 250 -> 3 stars, got {summary['quality_measure_rating']}")


# =====================================================================
# Corner/endpoints/star_summary_overall_rating_computed_read
# =====================================================================

def test_star_summary_overall_rating_five():
    """PRD §3.1: "The overall_star_rating starts from the health_inspection_rating, then
    adds 1 if the staffing_rating is at least 4 and subtracts 1 if it is at most 2, then
    adds 1 if the quality_measure_rating is at least 4 and subtracts 1 if it is at most
    2; the result is finally clamped to the range 1 through 5".

    Design: Corner/endpoints/star_summary_overall_rating_computed_read
    """
    facility = fixtures.create_facility(certified_bed_count=10, health_inspection_rating=4, staffing_rating=4)
    _seed_full_quality_measures(facility["id"])
    summary = validate_success(api_client.get_facility_star_summary(facility["id"], ADMIN))
    # health 4 + (staffing>=4 -> +1) + (qm>=4 -> +1) = 6 -> clamp to 5.
    assert summary["overall_star_rating"] == 5, (
        f"expected overall_star_rating 5, got {summary['overall_star_rating']}")


# =====================================================================
# Corner/entities/facility_create_returns_201_with_computed_defaults
# =====================================================================

def test_facility_create_computed_defaults():
    """PRD §3.1: "On creation, occupied_bed_count starts at 0 ... The two regulatory
    survey components, health_inspection_rating and staffing_rating, may be supplied on
    creation; each is a star value from 1 to 5 and each defaults to 3 when omitted".

    Design: Corner/entities/facility_create_returns_201_with_computed_defaults
    """
    data = validate_success(
        api_client.create_facility(
            f.create_facility_payload(name="Corner Fac", certified_bed_count=8), ADMIN),
        expected_status=201,
    )
    assert data["occupied_bed_count"] == 0, f"expected occupied_bed_count 0, got {data['occupied_bed_count']}"
    assert data["health_inspection_rating"] == 3, (
        f"health_inspection_rating must default to 3, got {data['health_inspection_rating']}")


# =====================================================================
# Corner/entities/facility_get_nonexistent_returns_not_found
# =====================================================================

def test_facility_get_nonexistent_not_found():
    """PRD §2.5: "The first identifier in the path that does not correspond to an
    existing resource causes immediate rejection with ERR_NOT_FOUND".

    Design: Corner/entities/facility_get_nonexistent_returns_not_found
    """
    validate_error(api_client.get_facility(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_NOT_FOUND.value)


# =====================================================================
# Corner/entities/resident_create_missing_required_field_returns_invalid_request
# =====================================================================

def test_resident_create_missing_medical_record_number():
    """PRD §3.2: "An AdmissionsCoordinator registers a prospective resident by providing
    the resident's full_name, a medical_record_number (unique across all residents), a
    date_of_birth, and a primary_facility_id".
    PRD §2.7: "the body must contain all required fields with valid types, enums, and
    ranges, else ERR_INVALID_REQUEST".

    Design: Corner/entities/resident_create_missing_required_field_returns_invalid_request
    """
    facility = fixtures.create_facility()
    payload = f.create_resident_payload(facility["id"])
    del payload["medical_record_number"]
    validate_error(api_client.create_resident(payload, COORD),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner/entities/resident_create_initial_status_prospective
# =====================================================================

def test_resident_create_initial_status_prospective():
    """PRD §3.2: "A newly registered resident begins in the PROSPECTIVE status".

    Design: Corner/entities/resident_create_initial_status_prospective
    """
    facility = fixtures.create_facility()
    data = validate_success(
        api_client.create_resident(f.create_resident_payload(facility["id"]), COORD),
        expected_status=201,
    )
    assert data["status"] == "PROSPECTIVE", f"expected PROSPECTIVE, got {data['status']}"


# =====================================================================
# Corner/entities/qualifying_stay_immutable_no_version_field
# =====================================================================

def test_qualifying_stay_persists_midnights_no_version():
    """PRD §3.2: "The system computes midnights_count as ... the UTC calendar date of
    the discharge minus the UTC calendar date of the admit, expressed in whole days".
    PRD §2.4: "A QualifyingStay carries only id and created_at; it has neither an
    updated_at nor a version field, reflecting that the prior acute-hospital stay it
    records is fixed once captured".

    Design: Corner/entities/qualifying_stay_immutable_no_version_field
    """
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    created = validate_success(
        api_client.create_qualifying_stay(
            resident["id"],
            f.create_qualifying_stay_payload(hospital_admit_at="2026-01-25T10:00:00Z",
                                             hospital_discharge_at="2026-01-29T10:00:00Z"), COORD),
        expected_status=201,
    )
    assert created["midnights_count"] == 4, f"expected 4 midnights, got {created['midnights_count']}"
    fetched = validate_success(api_client.get_qualifying_stay(created["id"], COORD))
    assert fetched["midnights_count"] == 4, "midnights_count must persist on re-read"
    assert "version" not in fetched, "QualifyingStay must NOT carry a version field"


# =====================================================================
# Corner/entities/list_residents_by_facility_pagination_envelope
# =====================================================================

def test_list_residents_by_facility_pagination_envelope():
    """PRD §3.2: "a primary_facility_id naming the facility the resident is registered
    against".
    PRD §2.3: "The total_count reflects the total number of matching resources before
    pagination is applied, and has_more is true when additional resources remain beyond
    the current page".

    Design: Corner/entities/list_residents_by_facility_pagination_envelope
    """
    facility = fixtures.create_facility()
    fixtures.create_resident(facility["id"])
    resp = api_client.list_residents(COORD, params={"primary_facility_id": facility["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more false, got {meta['has_more']}"


# =====================================================================
# Corner/validations/error_pasrr_level_ii_required_on_clear
# =====================================================================

def test_pasrr_level_ii_required_on_clear():
    """PRD §3.2: "a LEVEL_I screening whose has_serious_mental_illness_indicator is true
    may not be resolved directly to CLEARED — such a screening must first escalate to a
    Level II evaluation — and an attempt to clear it is rejected with
    ERR_PASRR_LEVEL_II_REQUIRED".

    Design: Corner/validations/error_pasrr_level_ii_required_on_clear
    """
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    pasrr = fixtures.create_pasrr(resident["id"], level="LEVEL_I", has_serious_mental_illness_indicator=True)
    validate_error(
        api_client.resolve_pasrr_screening(pasrr["id"], {"resolution": "CLEARED"}, COORD),
        ApiErrorId.ERR_PASRR_LEVEL_II_REQUIRED.value)


# =====================================================================
# Corner/rbac/therapist_cannot_create_admission_forbidden
# =====================================================================

def test_therapist_cannot_create_admission():
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE".

    Design: Corner/rbac/therapist_cannot_create_admission_forbidden
    """
    facility = fixtures.create_facility()
    resident = fixtures.create_resident(facility["id"])
    pasrr = fixtures.create_pasrr(resident["id"])
    payload = f.create_admission_payload(resident["id"], facility["id"], pasrr["id"], payer_source="PRIVATE")
    validate_error(api_client.create_admission(payload, THERAPIST),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =====================================================================
# Corner/rbac/billing_analyst_cannot_complete_assessment_forbidden
# =====================================================================

def test_billing_analyst_cannot_complete_assessment():
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE".

    Design: Corner/rbac/billing_analyst_cannot_complete_assessment_forbidden
    """
    facility, resident, pasrr, admission, qs = fixtures.create_active_admission(
        payer_source="MEDICARE_A", with_qualifying=True)
    assessment = fixtures.schedule_assessment(admission["id"])
    get_success_data(api_client.start_assessment(assessment["id"], {}, MDS))
    validate_error(api_client.complete_assessment(assessment["id"], {}, BILLING),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =====================================================================
# Corner/rbac/missing_headers_returns_unauthenticated
# =====================================================================

def test_missing_headers_returns_unauthenticated():
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers ... If either header is missing or empty, the request is rejected with
    ERR_UNAUTHENTICATED".

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    # No X-User-ID / X-User-Role headers (only Content-Type).
    anon_headers = {"Content-Type": "application/json"}
    resp = api_client.create_facility(
        f.create_facility_payload(name="Anon Fac"), anon_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
