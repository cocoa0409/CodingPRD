"""Reference-data CRUD, RBAC denials, ownership, the error envelope, and the
two optimistic-concurrency stale-version checks.

Covers credit-hour computation and defaults on program create, the student
enrolled side effect, not-found / required-field / duplicate / FK-not-found
errors, list pagination, the error envelope shape, role and ownership denials,
and the OCC ERR_STALE_ENROLLMENT_VERSION on both guarded writes.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NONEXISTENT_UUID,
    create_program, create_student, create_instructor, create_enrollment,
    create_approved_attendance, schedule_disbursement,
    setup_calculated_withdrawal_with_posted_disbursement,
    create_program_payload, create_student_payload, create_instructor_payload,
    create_enrollment_payload, create_exam_application_payload,
    create_disbursement_payload, create_attendance_payload,
    make_registrar_headers, make_financial_aid_officer_headers,
    make_instructor_headers, make_student_headers,
)

REGISTRAR = make_registrar_headers()
FAO = make_financial_aid_officer_headers()


# ==========================================================================
# entities / create_program_computes_credit_hours  (queue B)
# ==========================================================================
def test_create_program_computes_credit_hours(api):
    """PRD §3.1: "On program creation the server derives `credit_hours` once: it
    divides `total_clock_hours` by `clock_hours_per_credit` and takes the floor,
    truncating any fraction toward zero to yield an integer. For a 1500-hour
    program at the default divisor of 37.5 clock hours per credit, this yields 40
    credits."

    Design: Corner/entities/create_program_computes_credit_hours
    """
    data = validate_success(
        api.create_program(
            create_program_payload(
                total_clock_hours=1500, tuition_cents=1200000,
                kit_fee_cents=150000, lab_fee_cents=50000, clinic_phase_start_hour=300,
            ),
            REGISTRAR,
        ),
        201,
    )
    assert data["credit_hours"] == 40, f"credit_hours should be 40, got {data['credit_hours']}"


# ==========================================================================
# entities / create_program_clinic_phase_default_applies  (queue B)
# ==========================================================================
def test_create_program_defaults_apply(api):
    """PRD §3.1: "may supply `clock_hours_per_credit`, the divisor that converts
    clock hours to academic credits; when omitted it defaults to 37.5 ... A program
    may also supply `admin_fee_cap_cents` ...; when omitted it defaults to 15000
    cents." A 600-hour program at the default divisor yields 600/37.5 = 16 credits.

    Design: Corner/entities/create_program_clinic_phase_default_applies
    """
    data = validate_success(
        api.create_program(
            create_program_payload(
                name="Esthetics 600", total_clock_hours=600, tuition_cents=500000,
                kit_fee_cents=80000, lab_fee_cents=20000, clinic_phase_start_hour=150,
            ),
            REGISTRAR,
        ),
        201,
    )
    assert data["credit_hours"] == 16, f"credit_hours should be 16, got {data['credit_hours']}"
    assert data["admin_fee_cap_cents"] == 15000
    assert data["clock_hours_per_credit"] == 37.5


# ==========================================================================
# entities / enrollment_create_sets_student_enrolled  (queue B)
# ==========================================================================
def test_enrollment_create_sets_student_enrolled(api):
    """PRD §3.2: "A new enrollment begins in `ACTIVE` status, and creating it
    transitions the named student's `status` to `ENROLLED`."

    Design: Corner/entities/enrollment_create_sets_student_enrolled
    """
    program = create_program()
    student = create_student()
    create_enrollment(program=program, student=student)
    data = validate_success(api.get_student(student["id"], REGISTRAR))
    assert data["status"] == "ENROLLED"


# ==========================================================================
# entities / get_program_not_found  (queue B)
# ==========================================================================
def test_get_program_not_found(api):
    """PRD §2.6: "Any identifier embedded in the URL path is checked first, in path
    order, and the first one that does not resolve to an existing resource causes
    the request to be rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_program_not_found
    """
    validate_error(
        api.get_program(NONEXISTENT_UUID, REGISTRAR),
        ApiErrorId.ERR_NOT_FOUND.value,
    )


# ==========================================================================
# entities / create_student_missing_required_field  (queue B)
# ==========================================================================
def test_create_student_missing_email_rejected(api):
    """PRD §2.10: "then request-shape validation — required fields present, correct
    types, valid enum values, and numeric fields within their declared ranges
    (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "A **Student** is registered with a `full_name`, a contact `email`
    that must be unique across all students, and `ssn_last4`."

    Design: Corner/entities/create_student_missing_required_field
    """
    resp = api.create_student({"full_name": "No Email", "ssn_last4": "0000"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# entities / create_student_duplicate_email  (queue B)
# ==========================================================================
def test_create_student_duplicate_email_rejected(api):
    """PRD §3.1: "Attempting to register a student whose `email` already belongs to
    another student is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/create_student_duplicate_email
    """
    get_success_data(
        api.create_student(create_student_payload(email="dup@x.com"), REGISTRAR)
    )
    resp = api.create_student(create_student_payload(email="dup@x.com"), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ==========================================================================
# entities / create_instructor_duplicate_license  (queue B)
# ==========================================================================
def test_create_instructor_duplicate_license_rejected(api):
    """PRD §3.1: "Creating an instructor whose `license_number` duplicates an
    existing one is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/entities/create_instructor_duplicate_license
    """
    get_success_data(
        api.create_instructor(create_instructor_payload(license_number="INS-DUP"), REGISTRAR)
    )
    resp = api.create_instructor(
        create_instructor_payload(license_number="INS-DUP"), REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ==========================================================================
# entities / enrollment_create_invalid_enum_program_fk_not_found  (queue B)
# ==========================================================================
def test_enrollment_create_program_fk_not_found(api):
    """PRD §2.6: "After path identifiers, foreign keys carried in the request body
    are validated: a body foreign key that names a non-existent entity is rejected
    with `ERR_FK_NOT_FOUND`."

    Design: Corner/entities/enrollment_create_invalid_enum_program_fk_not_found
    """
    student = create_student()
    resp = api.create_enrollment(
        create_enrollment_payload(student["id"], NONEXISTENT_UUID),
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ==========================================================================
# entities / list_programs_pagination_envelope  (queue B)
# ==========================================================================
def test_list_programs_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object." With two programs and limit 1,
    total_count is 2 and has_more is true.

    Design: Corner/entities/list_programs_pagination_envelope
    """
    create_program(name="P1")
    create_program(name="P2", total_clock_hours=600, clinic_phase_start_hour=150)
    data, meta = validate_paginated(api.list_programs(REGISTRAR, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True


# ==========================================================================
# errors / error_envelope_shape_on_not_found  (queue B)
# ==========================================================================
def test_error_envelope_shape_on_not_found(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format ... `response_type`: `error` ... `data`: `error_id` ...
    `message`."

    Design: Corner/errors/error_envelope_shape_on_not_found
    """
    resp = api.get_enrollment(NONEXISTENT_UUID, REGISTRAR)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
    assert isinstance(error_data["message"], str) and len(error_data["message"].strip()) > 0


# ==========================================================================
# rbac / student_cannot_create_program  (queue B)
# ==========================================================================
def test_student_cannot_create_program(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`." Program creation is Registrar-only (§4).

    Design: Corner/rbac/student_cannot_create_program
    """
    student = create_student()
    resp = api.create_program(
        create_program_payload(name="Sneaky", tuition_cents=1),
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ==========================================================================
# rbac / instructor_cannot_post_disbursement  (queue B)
# ==========================================================================
def test_instructor_cannot_create_disbursement(api):
    """PRD §2.1: "The `FinancialAidOfficer` owns Title IV disbursements" and a role
    not permitted for an operation is rejected with `ERR_FORBIDDEN_ROLE`.

    Design: Corner/rbac/instructor_cannot_post_disbursement
    """
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=450,
    )
    resp = api.create_disbursement(
        create_disbursement_payload(enrollment["id"]),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ==========================================================================
# rbac / missing_auth_headers_unauthenticated  (queue B)
# ==========================================================================
def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    from test_helpers import build_user_headers
    resp = api.list_programs(build_user_headers("ghost-1", "Ghost"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ==========================================================================
# rbac / student_cannot_act_on_others_exam_application  (queue B)
# ==========================================================================
def test_student_cannot_submit_others_exam_application(api):
    """PRD §3.7: "A `Student` ... may act only on applications belonging to an
    enrollment they own — a student touching another enrollment's application is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/student_cannot_act_on_others_exam_application
    """
    program = create_program()
    student_a = create_student()
    student_b = create_student()
    enrollment = create_enrollment(
        program=program, student=student_a, scheduled_hours_to_date=100,
    )
    app = get_success_data(
        api.create_exam_application(
            create_exam_application_payload(
                enrollment["id"], mock_exam_avg=80, competency_signoff_pct=100,
            ),
            make_student_headers(student_a["id"]),
        )
    )
    resp = api.submit_exam_application(app["id"], make_student_headers(student_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ==========================================================================
# cross_cutting / occ_post_disbursement_stale_version  (queue B)
# ==========================================================================
def test_post_disbursement_stale_enrollment_version_rejected(api):
    """PRD §2.7: "Posting a disbursement requires `expected_enrollment_version` to
    equal the live `version` of the disbursement's owning enrollment. If a prior
    mutation — another disbursement post, an attendance approval that changed
    `actual_hours`, or a SAP evaluation — has advanced the enrollment's `version`
    since the client last read it, the post is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_post_disbursement_stale_version
    """
    from test_helpers import set_clock
    program = create_program()
    student = create_student()
    instructor = create_instructor()
    enrollment = create_enrollment(
        program=program, student=student, scheduled_hours_to_date=450,
    )
    create_approved_attendance(enrollment["id"], instructor, 405, scheduled_hours=405)
    # Capture the enrollment version right after the first approval.
    enr1 = validate_success(api.get_enrollment(enrollment["id"], FAO))
    stale_version = enr1["version"]
    set_clock("2026-06-01T00:00:00Z", FAO)
    dis = schedule_disbursement(
        enrollment["id"], period_hours=400, period_weeks=4,
        gross_amount_cents=600000, origination_fee_cents=0,
    )
    # Advance the enrollment version with a second attendance approval.
    create_approved_attendance(
        enrollment["id"], instructor, 10, scheduled_hours=10,
        session_date_iso="2026-05-02T00:00:00Z",
    )
    validate_error(
        api.post_disbursement(dis["id"], stale_version, FAO),
        ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value,
    )


# ==========================================================================
# cross_cutting / occ_finalize_withdrawal_stale_version  (queue B)
# ==========================================================================
def test_finalize_withdrawal_stale_enrollment_version_rejected(api):
    """PRD §2.7: "Finalizing a withdrawal likewise requires
    `expected_enrollment_version` to equal the live `version` of the owning
    enrollment; if a disbursement post or attendance approval has advanced that
    `version` between the moment the withdrawal was calculated and the finalize
    call, the finalize is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

    A second disbursement is scheduled then posted after the withdrawal is
    calculated, advancing the version; finalize on the stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_withdrawal_stale_version
    """
    from test_helpers import post_disbursement
    program, student, instructor, enrollment, dis, wd = (
        setup_calculated_withdrawal_with_posted_disbursement(
            actual_hours=405, scheduled_hours_to_date=450,
            gross_amount_cents=600000, origination_fee_cents=0,
        )
    )
    # Capture the stale version after the withdrawal was calculated.
    enr_stale = validate_success(api.get_enrollment(enrollment["id"], FAO))
    stale_version = enr_stale["version"]
    # Advance the enrollment version by scheduling + posting a second disbursement.
    dis2 = schedule_disbursement(
        enrollment["id"], payment_period=2, period_hours=400, period_weeks=4,
        gross_amount_cents=300000, origination_fee_cents=0,
    )
    post_disbursement(dis2["id"], enrollment["id"])
    validate_error(
        api.finalize_withdrawal(wd["id"], stale_version, FAO),
        ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value,
    )
