"""Resource creation defaults, required-field and enum validation, not-found,
filtered listing, RBAC denials, the user-context header check, and the logical
clock default.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    ADMIN,
    INTAKE,
    CLINICIAN,
    DIETITIAN,
    REVIEWER,
    fixtures as fx,
)


def test_create_facility_minimal_defaults_timezone_utc(api):
    """PRD §3.1: "created by an `Admin` with a `name` and an optional `timezone`
    label that defaults to `UTC`."
    PRD §2.4: "a `version` integer that begins at 1".

    Design: Corner/entities/create_facility_minimal_required_fields
    """
    resp = api.create_facility({"name": "Cedar EDT"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["name"] == "Cedar EDT", f"expected name 'Cedar EDT', got {data['name']}"
    assert data["timezone"] == "UTC", f"expected timezone UTC, got {data['timezone']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_create_program_missing_bed_capacity_invalid_request(api):
    """PRD §3.1: "each created with a `facility_id`, a `level_of_care`, and a
    `bed_capacity`."
    PRD §2.6: "a malformed body yields `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/create_program_missing_bed_capacity_returns_invalid_request
    """
    facility = fx.create_facility(name="Cedar EDT")
    resp = api.create_program(
        {"facility_id": facility["id"], "level_of_care": "PHP"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_program_invalid_level_of_care_rejected(api):
    """PRD §3.1: "The `level_of_care` is one of `RESIDENTIAL`, `PHP`, `IOP`, or
    `OP`."
    PRD §2.6: "Field-level request validation — enum membership ... is applied to
    create and update endpoints; a malformed body yields `ERR_INVALID_REQUEST`
    (HTTP 400)".

    Design: Corner/entities/create_program_invalid_level_of_care_enum_rejected
    """
    facility = fx.create_facility(name="Cedar EDT")
    resp = api.create_program(
        {"facility_id": facility["id"], "level_of_care": "DAYCARE",
         "bed_capacity": 5},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_admission_nonexistent_returns_not_found(api):
    """PRD §2.7: "The resource-specific not-found errors are: ... `ERR_ADMISSION_NOT_FOUND`
    for an admission".

    Design: Corner/entities/get_admission_nonexistent_returns_not_found
    """
    fx.create_facility(name="Cedar EDT")
    resp = api.get_admission("00000000-0000-4000-8000-000000000000", INTAKE)
    validate_error(resp, ApiErrorId.ERR_ADMISSION_NOT_FOUND.value)


def test_list_admissions_filtered_by_program(api):
    """PRD §2.7: "a parent's children are discovered by filtering the relevant
    list endpoint on a foreign-key query parameter".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object".

    Design: Corner/endpoints/list_admissions_filtered_by_program_reverse_reachability
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    resp = api.list_admissions(INTAKE, params={"program_id": program["id"]})
    data, meta = validate_paginated(resp)
    ids = [a["id"] for a in data]
    assert admission["id"] in ids, (
        f"expected admission {admission['id']} in filtered list, got {ids}"
    )
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"


def test_dietitian_cannot_create_assessment(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared
    role is not permitted to perform the requested operation, the request is
    rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "`Clinician` owns the clinical surface: assessments".

    Design: Corner/rbac/dietitian_cannot_create_assessment
    """
    facility = fx.create_facility(name="Cedar EDT")
    patient = fx.create_patient(facility["id"], full_name="Pat JJ")
    resp = api.create_assessment(
        {"patient_id": patient["id"], "facility_id": facility["id"],
         "medical_severity": 5, "behavioral_severity": 5,
         "psychiatric_severity": 4, "motivation_level": 6},
        DIETITIAN,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_clinician_cannot_sign_dietitian_discipline(api):
    """PRD §3.7: "The `THERAPY` and `MEDICAL` disciplines may be signed only by a
    `Clinician`, while the `DIETITIAN` discipline may be signed only by a
    `Dietitian`; signing with the wrong role is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/clinician_cannot_sign_dietitian_discipline
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"], full_name="Pat KK")
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    tp = validate_success(
        api.create_treatment_plan(
            {"admission_id": admission["id"], "facility_id": facility["id"],
             "goals_total": 3},
            CLINICIAN,
        ),
        expected_status=201,
    )
    resp = api.sign_treatment_plan(tp["id"], {"discipline": "DIETITIAN"}, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their operational
    capacity. If either header is missing or malformed, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.create_facility({"name": "NoAuth EDT"}, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_clock_default_before_set_is_jan_1_2026(api):
    """PRD §2.4: "The logical clock starts at `2026-01-01T00:00:00Z` and is moved
    only by an administrative clock-set capability".
    PRD §3.11: "`days_consumed` is the sum over every approved window of the
    elapsed whole days in that window up to the clock".

    Design: Corner/cross_cutting_complexity_layers/clock_default_before_set_is_jan_1_2026
    """
    # No clock-set: window [01-01, 01-08) has consumed zero days at the default.
    ctx = fx.setup_substrate_minimal_for_auth(los_days=7)
    data = validate_success(api.get_authorization(ctx["authorization"]["id"], REVIEWER))
    assert data["days_authorized"] == 7
    assert data["days_consumed"] == 0, f"expected 0, got {data['days_consumed']}"
    assert data["days_remaining"] == 7, f"expected 7, got {data['days_remaining']}"
