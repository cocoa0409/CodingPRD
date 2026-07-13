"""Programs, cohorts, family/application intake: creation, validation, defaults,
computed slot accounting, listing, and role gating (PRD §2.1, §2.3, §2.5, §3.1, §3.2).

Breadth coverage translated from the corner-design entities / endpoints / rbac
sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, build_user_headers,
    create_program_payload, create_cohort_payload, create_family_payload,
    create_application_payload, create_program, create_cohort, create_family,
    assert_program, assert_cohort, assert_application,
)

PA = TEST_USERS["program_admin_headers"]
ES = TEST_USERS["enrollment_specialist_headers"]


def test_create_program_returns_201_and_echoes_program_type(api):
    """PRD §3.1: "A `ProgramAdmin` establishes a grantee program by supplying its
    `name`, its `program_type` (one of `HEAD_START`, `PRE_K`, or `EARLY_HEAD_START`)".
    PRD §4: "Endpoints that create a new, stand-alone resource return `201 Created`."

    Design: Corner/entities/create_program_returns_201_with_system_fields
    """
    resp = api.create_program(
        create_program_payload(program_type="HEAD_START"), PA)
    data = validate_success(resp, expected_status=201)
    assert data["program_type"] == "HEAD_START"
    assert_program(data)


def test_get_program_nonexistent_returns_not_found(api):
    """PRD §2.9: "every referenced `program_id`, `cohort_id`, `family_id`,
    `enrollment_id`, and `application_id` must resolve to an existing resource, and
    the system returns the not-found error matching the resource that failed to
    resolve — `ERR_PROGRAM_NOT_FOUND`".

    Design: Corner/entities/get_program_nonexistent_returns_not_found
    """
    resp = api.get_program("00000000-0000-4000-8000-000000000000", PA)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)


def test_create_family_missing_categorical_returns_validation(api):
    """PRD §3.2: "An `EnrollmentSpecialist` or a `Family` opens a household record by
    providing the `guardian_name`, the `household_size` (the number of persons in the
    household, at least one, which drives the poverty threshold), the self-declared
    `annual_income_cents` (gross annual household income in cents, zero or greater), and
    the `categorical_eligibility` value (one of `NONE`, `TANF`, `SSI`, `SNAP`, or
    `FOSTER` — a categorical program enrollment that confers eligibility independent of
    income)."
    PRD §2.10: "Structural body validation — required fields present and well-typed, enum
    values within their declared domains, and numeric fields within declared bounds — is
    evaluated last and, when it fails, yields `ERR_VALIDATION` with HTTP status 400."

    Design: Corner/entities/create_family_missing_required_categorical_returns_validation
    """
    payload = {"guardian_name": "B", "household_size": 3, "annual_income_cents": 800000}
    resp = api.create_family(payload, ES)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_family_homeless_status_defaults_false(api):
    """PRD §3.2: "The household may also declare `homeless_status`, a McKinney-Vento
    homeless determination that defaults to false and, when true, confers categorical
    eligibility and the highest priority weight."

    Design: Corner/entities/family_homeless_status_defaults_false
    """
    resp = api.create_family(
        create_family_payload(categorical_eligibility="TANF"), ES)
    data = validate_success(resp, expected_status=201)
    assert data["homeless_status"] is False


def test_cohort_slot_accounting_computed_on_create(api):
    """PRD §2.5: "Its `available_slots` is `funded_slots` minus `filled_slots` minus
    `reserved_slots`, and by construction of the accounting it is never negative. Its
    `selection_status` is a pure function of that arithmetic: `OPEN` when
    `available_slots` is greater than zero, otherwise `FULL`."
    PRD §3.1: "On creation, if `funded_slots` is greater than zero the cohort's
    `selection_status` derives to `OPEN`."

    Design: Corner/entities/cohort_slot_accounting_computed_on_create
    """
    program = create_program()
    resp = api.create_cohort(create_cohort_payload(program["id"], funded_slots=3), PA)
    data = validate_success(resp, expected_status=201)
    assert data["available_slots"] == 3
    assert data["filled_slots"] == 0
    assert data["selection_status"] == "OPEN"
    assert_cohort(data)


def test_application_created_in_draft_status(api):
    """PRD §3.2: "A newly created application begins in `DRAFT`. At this stage the
    system-managed fields `verified_income_cents`, `status`, `eligibility_category`,
    `income_ratio`, `age_months_at_cutoff`, `priority_points`, `submitted_at`, and
    `waitlisted_at` are not yet populated by intake".

    Design: Corner/entities/application_status_draft_and_system_fields_on_create
    """
    program = create_program()
    cohort = create_cohort(program["id"])
    family = create_family()
    resp = api.create_application(
        create_application_payload(program["id"], cohort["id"], family["id"]), ES)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert_application(data)


def test_create_cohort_invalid_age_band_enum_returns_validation(api):
    """PRD §3.1: "A cohort names its parent program through `program_id` and carries an
    `age_band` (one of `INFANT`, `TODDLER`, `PRESCHOOL_3`, or `PRESCHOOL_4`)".
    PRD §2.10: "Structural body validation — required fields present and well-typed, enum
    values within their declared domains, and numeric fields within declared bounds — is
    evaluated last and, when it fails, yields `ERR_VALIDATION` with HTTP status 400."

    Design: Corner/entities/create_cohort_invalid_enum_age_band_returns_validation
    """
    program = create_program()
    resp = api.create_cohort(
        create_cohort_payload(program["id"], age_band="TEENAGER"), PA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_create_application_unknown_family_returns_not_found(api):
    """PRD §2.9: "The same principle governs foreign keys supplied in a request body:
    every referenced `program_id`, `cohort_id`, `family_id`, `enrollment_id`, and
    `application_id` must resolve to an existing resource, and the system returns the
    not-found error matching the resource that failed to resolve — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_COHORT_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`".

    Design: Corner/entities/create_application_unknown_family_returns_not_found
    """
    program = create_program()
    cohort = create_cohort(program["id"])
    payload = create_application_payload(
        program["id"], cohort["id"], "00000000-0000-4000-8000-000000000000")
    resp = api.create_application(payload, ES)
    validate_error(resp, ApiErrorId.ERR_FAMILY_NOT_FOUND)


def test_list_programs_pagination_has_more(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_programs_pagination_has_more
    """
    create_program(name="HS1", program_type="HEAD_START")
    create_program(name="HS2", program_type="PRE_K")
    resp = api.list_programs(PA, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_enrollment_specialist_cannot_create_program(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/enrollment_specialist_cannot_create_program_unauthorized
    """
    resp = api.create_program(create_program_payload(), ES)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent or `X-User-Role` is not one of these four
    known roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    program = create_program()
    resp = api.get_program(program["id"], build_user_headers("someone", "Anonymous"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
