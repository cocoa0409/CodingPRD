"""Course/catalog creation, defaults, type/uniqueness constraints, not-found, and
listing/pagination. Queue B (corner) — entities section.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    ApiErrorId,
    NONEXISTENT_UUID,
    set_clock,
    create_course,
    create_published_course,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Corner/entities/create_course_returns_201_with_system_fields
# ===========================================================================
def test_create_course_returns_201_with_system_fields(api):
    """PRD §2.4: "The version begins at 1 on creation and increments by one on every
    mutation of that resource."
    PRD §3.1: "A course is born DRAFT."

    Design: Corner/entities/create_course_returns_201_with_system_fields
    """
    set_clock()
    resp = api.create_course(
        f.create_course_payload(code="C-CREATE", title="Create", content_type="SCORM", passing_score=70),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", f"new course is DRAFT, got {data['status']}"
    assert data["version"] == 1, f"new course version is 1, got {data['version']}"
    assert data["passing_score"] == 70


# ===========================================================================
# Corner/entities/get_course_not_found_returns_404
# ===========================================================================
def test_get_course_with_unknown_id_returns_404(api):
    """PRD §2.6: "the first identifier in the path that does not resolve to an existing
    row causes an immediate ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_course_not_found_returns_404
    """
    resp = api.get_course(NONEXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/create_course_missing_required_field_returns_400
# ===========================================================================
def test_create_course_missing_passing_score_returns_400(api):
    """PRD §2.7: "write endpoints validate the shape of their payload: required fields
    must be present and well-typed ... A violation here is ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_course_missing_required_field_returns_400
    """
    resp = api.create_course(
        {"code": "C-MISS", "title": "Miss", "content_type": "SCORM"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/create_course_defaults_applied
# ===========================================================================
def test_create_course_applies_declared_defaults(api):
    """PRD §3.1: "max_attempts defaults to 3 ... grading_policy defaults to HIGHEST_SCORE
    (the alternative is LATEST_ATTEMPT), ceu_policy defaults to STANDARD (the alternative
    is SCORE_WEIGHTED)."

    Design: Corner/entities/create_course_defaults_applied
    """
    set_clock()
    data = get_success_data(
        api.create_course(
            {"code": "C-DEF", "title": "Def", "content_type": "SCORM", "passing_score": 60}, ADMIN
        )
    )
    assert data["max_attempts"] == 3, f"default max_attempts 3, got {data['max_attempts']}"
    assert data["grading_policy"] == "HIGHEST_SCORE", f"default HIGHEST_SCORE, got {data['grading_policy']}"
    assert data["ceu_policy"] == "STANDARD", f"default STANDARD, got {data['ceu_policy']}"


# ===========================================================================
# Corner/entities/course_invalid_enum_content_type_returns_400
# ===========================================================================
def test_create_course_invalid_content_type_returns_400(api):
    """PRD §2.7: "enum-valued fields must hold one of their declared values ... A course's
    content_type is SCORM or XAPI."

    Design: Corner/entities/course_invalid_enum_content_type_returns_400
    """
    resp = api.create_course(
        {"code": "C-ENUM", "title": "Enum", "content_type": "PDF", "passing_score": 70}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner/entities/duplicate_course_code_returns_409
# ===========================================================================
def test_duplicate_course_code_returns_409(api):
    """PRD §3.1: "A duplicate code is ERR_DUPLICATE." (code "unique, case-sensitive")

    Design: Corner/entities/duplicate_course_code_returns_409
    """
    set_clock()
    get_success_data(
        api.create_course(
            {"code": "DUP", "title": "First", "content_type": "SCORM", "passing_score": 70}, ADMIN
        )
    )
    resp = api.create_course(
        {"code": "DUP", "title": "Second", "content_type": "XAPI", "passing_score": 80}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


# ===========================================================================
# Corner/entities/employee_self_referential_manager_not_found_returns_404
# ===========================================================================
def test_create_employee_with_unknown_manager_returns_404(api):
    """PRD §2.6: "Foreign keys carried in a request body — a course_id, learning_path_id,
    employee_id, prerequisite_course_id, or manager_id — are likewise resolved against
    existing rows, and an unresolved body FK is also ERR_NOT_FOUND."

    Design: Corner/entities/employee_self_referential_manager_not_found_returns_404
    """
    resp = api.create_employee(
        {"email": "orphan@x.com", "full_name": "Orphan", "department": "HR",
         "job_role": "IC", "manager_id": NONEXISTENT_UUID},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner/entities/list_courses_pagination_envelope
# ===========================================================================
def test_list_courses_honors_limit_and_reports_pagination_meta(api):
    """PRD §2.3: "The limit parameter caps the number of items returned ... Every list
    response reports limit, offset, total_count, and has_more inside the meta object of
    the envelope."

    Design: Corner/entities/list_courses_pagination_envelope
    """
    set_clock()
    create_course(code="PG-1", title="Pg1")
    create_course(code="PG-2", title="Pg2")
    resp = api.list_courses(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit 1 → one item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more should be true when more remain"
