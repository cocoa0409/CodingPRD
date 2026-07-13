"""Onboarding, entity creation defaults, and basic catalog/validation reads."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    make_creator_headers, make_student_headers,
    assert_creator,
    fixtures as fx,
)


def test_creator_onboarding_returns_201_active_zero_ledger(api, admin_headers):
    """PRD §3.1: "the new `Creator` begins in `ACTIVE` status with every ledger figure
    at zero." PRD §2.4: "`version` (an integer that begins at 1 and increases by one
    each time the resource is mutated)."

    Design: Corner/entities/creator_creation_returns_201_with_fields
    """
    resp = api.create_creator({"email": "ada@x.com", "display_name": "Ada"}, admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_creator(data)
    assert data["status"] == "ACTIVE"
    assert data["available_for_payout_cents"] == 0
    assert data["lifetime_gross_cents"] == 0
    assert data["version"] == 1


def test_get_unknown_course_returns_404(api, admin_headers):
    """PRD §2.1: "every id named in the path exists, checked left-to-right, else that
    entity's not-found error"

    Design: Corner/entities/course_get_non_existent_not_found
    """
    resp = api.get_course(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_FOUND.value)


def test_enrollment_missing_price_plan_id_returns_400(api):
    """PRD §2.1: "the request body and query are well-formed with required fields
    present and enums and types valid, else `ERR_INVALID_REQUEST`"

    Design: Corner/entities/enrollment_missing_required_field_returns_400
    """
    creator = fx.create_creator()
    student = fx.create_student()
    course = fx.create_course(creator["id"], title="A")
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course["id"]},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lesson_is_published_defaults_true_and_counts(api):
    """PRD §3.2: "A lesson may set `is_published` (whether it counts toward the
    curriculum and toward progress, defaulting to true)" PRD §3.2: "Adding a lesson
    recomputes the parent course's `published_lesson_count` — the number of its lessons
    with `is_published` true"

    Design: Corner/entities/lesson_default_is_published_applied
    """
    creator = fx.create_creator()
    course = fx.create_course(creator["id"], title="A")
    lesson = fx.create_lesson(course["id"], creator["id"], title="L1", position=1)
    assert lesson["is_published"] is True
    got = validate_success(api.get_course(course["id"], make_creator_headers(creator["id"])))
    assert got["published_lesson_count"] == 1


def test_new_course_status_is_draft(api):
    """PRD §3.2: "A new `Course` begins in `DRAFT`."

    Design: Corner/entities/course_system_status_ignores_client_input
    """
    creator = fx.create_creator()
    resp = api.create_course({"creator_id": creator["id"], "title": "A"},
                             make_creator_headers(creator["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_coupon_invalid_discount_type_returns_400(api):
    """PRD §2.1: "the request body and query are well-formed with required fields
    present and enums and types valid, else `ERR_INVALID_REQUEST`"

    Design: Corner/entities/coupon_invalid_enum_returns_400
    """
    creator = fx.create_creator()
    course = fx.create_course(creator["id"], title="A")
    resp = api.create_coupon(
        {"course_id": course["id"], "code": "X", "discount_type": "BOGUS",
         "discount_value": 10, "max_redemptions": 5,
         "starts_at": "2026-01-01T00:00:00Z", "expires_at": "2026-12-31T00:00:00Z"},
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_course_set_status_invalid_enum_value_returns_422(api):
    """PRD §3.2: "When a set-status request names a value outside the course's status
    enum, it is rejected with `ERR_INVALID_STATUS_VALUE`."

    Design: Corner/errors/set_status_invalid_value_returns_422
    """
    creator = fx.create_creator()
    course = fx.create_course(creator["id"], title="A")
    resp = api.set_course_status(course["id"], {"status": "LIVE"},
                                 make_creator_headers(creator["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATUS_VALUE.value)


def test_student_cannot_create_course_returns_403(api):
    """PRD §2.1: "When a syntactically valid request names a role that is not permitted
    to perform the requested operation, the platform responds with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/student_cannot_create_course_returns_403
    """
    student = fx.create_student()
    resp = api.create_course({"creator_id": student["id"], "title": "A"},
                             make_student_headers(student["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_list_enrollments_returns_paginated_array(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources." PRD §2.3: "Every list response reports `limit`, `offset`,
    `total_count`, and `has_more` in the envelope's `meta` object, where `total_count`
    is the size of the full filtered set"

    Design: Corner/endpoints/list_enrollments_returns_paginated_array
    """
    ctx = fx.setup_enrollment()
    resp = api.list_enrollments(make_creator_headers(ctx["creator"]["id"]),
                                params={"course_id": ctx["course"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(data) == 1
