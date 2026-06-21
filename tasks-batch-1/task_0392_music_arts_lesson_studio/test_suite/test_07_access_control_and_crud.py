"""Role-based access control, authentication, and basic CRUD / validation corners
(studio creation defaults, required fields, enum validity, not-found, listing).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_studio_payload,
    create_family_payload,
    create_student_payload,
    create_instructor_payload,
    create_room_payload,
    create_enrollment_payload,
    create_invoice_payload,
    setup_active_enrollment,
    setup_roster,
    create_studio,
    create_enrollment as build_enrollment,
    make_parent_guardian_headers,
    make_instructor_headers,
    assert_studio,
)

ADMIN = TEST_USERS["studio_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Corner / rbac / parentguardian_cannot_create_instructor
# ===========================================================================
def test_parentguardian_cannot_create_instructor(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD 4 lists `POST
    /studios/{studioId}/instructors` as authorized for `StudioAdmin` only.

    Design: Corner/rbac/parentguardian_cannot_create_instructor
    """
    studio = create_studio()
    sid = studio["id"]
    family = get_success_data(api.create_family(sid, create_family_payload(), ADMIN))
    res = api.create_instructor(
        sid,
        create_instructor_payload(
            instruments=["PIANO"],
            weekly_availability=[{"weekday": 0, "start_min": 0, "end_min": 1440}],
            hourly_rate_cents=6000,
        ),
        make_parent_guardian_headers(family["id"]),
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ===========================================================================
# Corner / rbac / instructor_cannot_finalize_invoice
# ===========================================================================
def test_instructor_cannot_finalize_invoice(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." PRD 4 lists `POST
    /studios/{studioId}/invoices/{invoiceId}/finalize` as authorized for `BillingClerk`
    only.

    Design: Corner/rbac/instructor_cannot_finalize_invoice
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment()
    sid = studio["id"]
    inv = get_success_data(
        api.create_invoice(sid, create_invoice_payload(enr["id"], "2026-01"), BILLING)
    )
    res = api.finalize_invoice(sid, inv["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


# ===========================================================================
# Corner / rbac / missing_user_context_returns_401
# ===========================================================================
def test_missing_user_context_returns_401(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_returns_401
    """
    studio = create_studio()
    sid = studio["id"]
    res = api.create_family(sid, create_family_payload(household_name="NoAuth"), {})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=401)


# ===========================================================================
# Corner / entities / create_studio_returns_201_with_defaults
# ===========================================================================
def test_create_studio_returns_201_with_defaults(api):
    """PRD 2.5: "its `status` is `OPEN` at creation". PRD 2.5: "The
    `makeup_credit_cap_per_enrollment` is the maximum number of `OUTSTANDING` makeup
    credits a single enrollment may hold concurrently, defaulting to 3. The
    `cancellation_notice_hours` is the minimum number of hours before a lesson's start
    that a cancellation must occur to earn a makeup credit, defaulting to 24."

    Design: Corner/entities/create_studio_returns_201_with_defaults
    """
    res = api.create_studio(create_studio_payload(name="MyStudio"), ADMIN)
    studio = validate_success(res, 201)
    assert_studio(studio)
    assert studio["status"] == "OPEN"
    assert studio["makeup_credit_cap_per_enrollment"] == 3
    assert studio["cancellation_notice_hours"] == 24


# ===========================================================================
# Corner / entities / create_enrollment_missing_required_field_returns_422
# ===========================================================================
def test_create_enrollment_missing_required_field_returns_422(api):
    """PRD 2.6: "request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422, raised
    when a required field is missing, a type or enum value is invalid, or a supplied
    window has its end at or before its start)." PRD 3.2 lists `duration_min` among the
    required enrollment-creation inputs.

    Design: Corner/entities/create_enrollment_missing_required_field_returns_422
    """
    studio, family, student, instructor, room = setup_roster()
    sid = studio["id"]
    payload = create_enrollment_payload(
        student["id"], instructor["id"], room["id"], instrument="PIANO", weekday=0, start_min=600
    )
    del payload["duration_min"]
    res = api.create_enrollment(sid, payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ===========================================================================
# Corner / entities / create_enrollment_invalid_instrument_enum_returns_422
# ===========================================================================
def test_create_enrollment_invalid_instrument_enum_returns_422(api):
    """PRD 2.6: "request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422, raised
    when a required field is missing, a type or enum value is invalid, or a supplied
    window has its end at or before its start)." PRD 3.2: the enrollment `instrument` is
    "one of the six instrument values".

    Design: Corner/entities/create_enrollment_invalid_instrument_enum_returns_422
    """
    studio, family, student, instructor, room = setup_roster()
    sid = studio["id"]
    res = api.create_enrollment(
        sid,
        create_enrollment_payload(
            student["id"], instructor["id"], room["id"],
            instrument="KAZOO", weekday=0, start_min=600, duration_min=60,
        ),
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ===========================================================================
# Corner / entities / get_enrollment_nonexistent_returns_404
# ===========================================================================
def test_get_enrollment_nonexistent_returns_404(api):
    """PRD 2.6: "Only then is the sub-resource identifier validated, yielding the
    not-found error specific to that resource type — `ERR_FAMILY_NOT_FOUND` for an
    unknown `familyId` ... `ERR_ENROLLMENT_NOT_FOUND` for `enrollmentId` ... — each HTTP
    404."

    Design: Corner/entities/get_enrollment_nonexistent_returns_404
    """
    studio = create_studio()
    sid = studio["id"]
    res = api.get_enrollment(sid, "00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_ENROLLMENT_NOT_FOUND", expected_status=404)


# ===========================================================================
# Corner / entities / list_families_paginated_envelope
# ===========================================================================
def test_list_families_paginated_envelope(api):
    """PRD 2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_families_paginated_envelope
    """
    studio = create_studio()
    sid = studio["id"]
    get_success_data(api.create_family(sid, create_family_payload(household_name="Solo"), ADMIN))
    data, meta = validate_paginated(api.list_families(sid, ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===========================================================================
# Corner / errors / cross_studio_reference_rejected
# ===========================================================================
def test_cross_studio_reference_rejected(api):
    """PRD 2.6: "on enrollment creation, recital-registration creation, and
    instrument-rental creation, any foreign key in the body must reference a sibling
    that belongs to this same studio ... A body that references an entity outside this
    studio is rejected with `ERR_CROSS_STUDIO_REFERENCE` (HTTP 422)."

    Design: Corner/errors/cross_studio_reference_rejected
    """
    studio_a = create_studio()
    studio_b = create_studio()
    sa, sb = studio_a["id"], studio_b["id"]
    family = get_success_data(api.create_family(sa, create_family_payload(), ADMIN))
    student = get_success_data(api.create_student(sa, create_student_payload(family["id"]), ADMIN))
    room = get_success_data(api.create_room(sa, create_room_payload(supported_instruments=["PIANO"]), ADMIN))
    # Instructor lives in studio B.
    instructor_b = get_success_data(
        api.create_instructor(
            sb,
            create_instructor_payload(
                instruments=["PIANO"],
                weekly_availability=[{"weekday": 0, "start_min": 0, "end_min": 1440}],
                hourly_rate_cents=6000,
            ),
            ADMIN,
        )
    )
    res = api.create_enrollment(
        sa,
        create_enrollment_payload(
            student["id"], instructor_b["id"], room["id"],
            instrument="PIANO", weekday=0, start_min=600, duration_min=60,
        ),
        ADMIN,
    )
    validate_error(res, "ERR_CROSS_STUDIO_REFERENCE", expected_status=422)
