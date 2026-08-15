"""Entity-level claims: declared defaults, computed fields at creation,
not-found routing, the pagination envelope, and the success/error envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_high_school,
    assert_invoice,
    assert_placement_record,
    assert_same_instant,
    create_high_school,
    create_hs_term,
    create_college_term,
    create_course,
    create_instructor,
    create_offering,
    create_placement_record,
    create_student,
    create_term_payload,
    api_client,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_high_school_applies_default_status(api, admin_headers):
    """PRD 3.1: "A `DualCreditAdmin` onboards a partner high school by creating a
    `HighSchool` with a `name` and a `district_code`."
    PRD 3.1: "The school's `status` starts at `ACTIVE`."

    Design: Corner/entities/create_high_school_applies_default_status
    """
    response = api.create_high_school(
        {"name": "Northview HS", "district_code": "NV-01"}, admin_headers
    )
    school = validate_success(response, 201)
    assert_high_school(school)
    assert school["status"] == "ACTIVE", (
        f"Expected status ACTIVE (system default), got {school['status']}"
    )


def test_create_term_missing_required_field_rejected(api, admin_headers):
    """PRD 3.1: "Each term carries `name`, `start_date`, `end_date`, `add_deadline`,
    `drop_deadline`, and `withdraw_deadline`, subject to the date-ordering and
    overlap rules of §2.4."
    PRD 2.10: "Next come request-shape validation (priority 4) — required fields,
    types, enum members, numeric ranges, term date ordering — and pagination
    parameters (also priority 4, for list endpoints)."
    PRD 2.4: "A violation is a malformed request rejected with `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/entities/create_term_missing_required_field_rejected
    """
    payload = create_term_payload("COLLEGE")
    del payload["end_date"]
    response = api.create_term(payload, admin_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_create_term_invalid_enum_rejected(api, admin_headers):
    """PRD 2.4: "Every `CourseOffering` references a pair of `AcademicTerm` records:
    one whose `institution_type` is `COLLEGE` and one whose `institution_type` is
    `HIGH_SCHOOL`."
    PRD 2.10: "Next come request-shape validation (priority 4) — required fields,
    types, enum members, numeric ranges, term date ordering — and pagination
    parameters (also priority 4, for list endpoints)."
    PRD 2.4: "A violation is a malformed request rejected with `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/entities/create_term_invalid_enum_rejected
    """
    payload = create_term_payload("COLLEGE")
    payload["institution_type"] = "UNIVERSITY"
    response = api.create_term(payload, admin_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_term_date_ordering_rejected(api, admin_headers):
    """PRD 2.4: "Every `AcademicTerm` enforces an internal date ordering at creation,
    exposed on the resource as the system-maintained `date_ordering` invariant note:
    `start_date` strictly precedes `add_deadline`, which is at or before
    `drop_deadline`, which is at or before `withdraw_deadline`, which is at or
    before `end_date`."
    PRD 2.4: "A violation is a malformed request rejected with `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/entities/term_date_ordering_rejected
    """
    payload = create_term_payload(
        "COLLEGE", add_deadline="2026-08-01T00:00:00Z"  # precedes start_date 2026-08-15
    )
    response = api.create_term(payload, admin_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_offering_computed_seat_counters_at_creation(api, admin_headers):
    """PRD 3.4: "The administrator creates one with `course_id`, `college_term_id`,
    `hs_term_id`, `high_school_id`, `instructor_id`, `capacity` (an integer at
    least 1), and an optional `delivery_mode` defaulting to `HS_CAMPUS`, one of
    `HS_CAMPUS`, `COLLEGE_CAMPUS`, or `ONLINE`."
    PRD 3.4: "A new offering's `status` is `DRAFT`, `seats_taken` is 0, and
    `seats_available` equals `capacity`."

    Design: Corner/entities/offering_computed_seat_counters_at_creation
    """
    school = create_high_school()
    college_term = create_college_term()
    hs_term = create_hs_term(school["id"])
    course = create_course()
    instructor = create_instructor(school["id"])

    response = api.create_offering(
        {
            "course_id": course["id"],
            "college_term_id": college_term["id"],
            "hs_term_id": hs_term["id"],
            "high_school_id": school["id"],
            "instructor_id": instructor["id"],
            "capacity": 7,
        },
        admin_headers,
    )
    offering = validate_success(response, 201)
    assert offering["status"] == "DRAFT", f"Expected DRAFT, got {offering['status']}"
    assert offering["delivery_mode"] == "HS_CAMPUS", (
        f"Expected default delivery_mode HS_CAMPUS, got {offering['delivery_mode']}"
    )
    assert offering["seats_taken"] == 0, f"Expected seats_taken 0, got {offering['seats_taken']}"
    assert offering["seats_available"] == 7, (
        f"Expected seats_available == capacity (7), got {offering['seats_available']}"
    )


def test_student_gpa_fields_initialize_zero(api, coordinator_headers):
    """PRD 3.5: "The student's `status` starts at `ELIGIBLE`, and both `college_gpa`
    and `hs_gpa` start at 0.000."

    Design: Corner/entities/student_gpa_fields_initialize_zero
    """
    school = create_high_school()
    response = api.create_student(
        {"full_name": "Jamie Diaz", "high_school_id": school["id"], "grade_level": 12},
        coordinator_headers,
    )
    student = validate_success(response, 201)
    assert student["status"] == "ELIGIBLE", f"Expected ELIGIBLE, got {student['status']}"
    assert student["college_gpa"] == 0, f"Expected college_gpa 0.000, got {student['college_gpa']}"
    assert student["hs_gpa"] == 0, f"Expected hs_gpa 0.000, got {student['hs_gpa']}"


def test_placement_record_expiry_computed(api, coordinator_headers):
    """PRD 3.2: "The system computes `expires_at` as `taken_at` plus 730 days."
    PRD 2.6: "Three resources are deliberately lighter-weight and carry only `id`
    and `created_at`, with no `updated_at` and no `version`: `Prerequisite`,
    `PlacementRecord`, and `Payment`."

    Design: Corner/entities/placement_record_expiry_computed
    """
    school = create_high_school()
    student = create_student(school["id"])
    response = api.create_placement_record(
        {
            "student_id": student["id"],
            "exam_code": "MATH",
            "score": 85,
            "taken_at": "2026-08-01T00:00:00Z",
        },
        coordinator_headers,
    )
    record = validate_success(response, 201)
    assert_placement_record(record)
    assert_same_instant(
        record["expires_at"], "2028-07-31T00:00:00Z", "PlacementRecord.expires_at"
    )


def test_get_nonexistent_student_returns_not_found(api, admin_headers):
    """PRD 2.9: "Requests that carry resource identifiers in the path validate them
    left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource."

    Design: Corner/entities/get_nonexistent_student_returns_not_found
    """
    response = api.get_student(NON_EXISTENT_UUID, admin_headers)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_pagination_envelope_and_bounds(api, admin_headers, coordinator_headers):
    """PRD 2.3: "List endpoints accept the query parameters `limit` and `offset`.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
    defaults to 0 and must be at least 0."
    PRD 2.3: "Out-of-range pagination parameters are rejected with
    `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)."
    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_pagination_envelope_and_bounds
    """
    school = create_high_school()
    create_student(school["id"], full_name="Alpha One", grade_level=11)
    create_student(school["id"], full_name="Beta Two", grade_level=12)

    data, meta = validate_paginated(
        api.list_students(admin_headers, params={"limit": 1, "offset": 0})
    )
    assert len(data) == 1, f"Expected exactly 1 student on the first page, got {len(data)}"
    assert meta["limit"] == 1, f"Expected meta.limit 1, got {meta['limit']}"
    assert meta["offset"] == 0, f"Expected meta.offset 0, got {meta['offset']}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "Expected has_more true with one student unpaged"

    response = api.list_students(admin_headers, params={"limit": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS.value)


def test_create_student_unknown_school_returns_not_found(api, coordinator_headers):
    """PRD 2.9: "After the path is fully resolved, body-supplied foreign keys are
    validated in their declared input order, again with `ERR_NOT_FOUND` on the
    first miss."

    Design: Corner/entities/create_student_unknown_school_returns_not_found
    """
    response = api.create_student(
        {"full_name": "Jamie Diaz", "high_school_id": NON_EXISTENT_UUID, "grade_level": 12},
        coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_fk_reverse_reachability_lists(api, admin_headers):
    """PRD 2.9: "Requests that carry resource identifiers in the path validate them
    left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not resolve to an existing resource. After the path is fully resolved,
    body-supplied foreign keys are validated in their declared input order, again
    with `ERR_NOT_FOUND` on the first miss."
    PRD 2.2: "The `data` field contains the resource object or an array of resource
    objects."
    Query-string filters are neither path identifiers nor body foreign keys, so a
    filtered list whose filter matches nothing returns an empty array page.

    Design: Corner/entities/fk_reverse_reachability_lists
    """
    enrollments, _meta = validate_paginated(
        api.list_enrollments(admin_headers, params={"offering_id": NON_EXISTENT_UUID})
    )
    assert enrollments == [], f"Expected empty array, got {enrollments}"

    invoices, _meta = validate_paginated(
        api.list_invoices(admin_headers, params={"enrollment_id": NON_EXISTENT_UUID})
    )
    assert invoices == [], f"Expected empty array, got {invoices}"

    entries, _meta = validate_paginated(
        api.list_transcript_entries(admin_headers, params={"enrollment_id": NON_EXISTENT_UUID})
    )
    assert entries == [], f"Expected empty array, got {entries}"


def test_success_and_error_envelope_shape(api, admin_headers):
    """PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/success_and_error_envelope_shape
    """
    create_response = api.create_high_school(
        {"name": "Northview HS", "district_code": "NV-01"}, admin_headers
    )
    created_id = validate_success(create_response, 201)["id"]
    body = create_response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["id"] == created_id

    error_response = api.get_course(NON_EXISTENT_UUID, admin_headers)
    validate_error(error_response, ApiErrorId.ERR_NOT_FOUND.value, 404)
    error_body = error_response.json()
    assert error_body["response_type"] == "error"
    assert error_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error_body["data"]["message"], str)
    assert len(error_body["data"]["message"].strip()) > 0
