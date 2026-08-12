"""Student enrollment: defaults, schema validation, retrieval, listing."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_student, create_student_payload,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["district_admin_headers"]
REF = TEST_USERS["school_referrer_headers"]
CLS = TEST_USERS["school_classifier_headers"]


def test_student_creation_applies_defaults(api):
    """PRD §3.1: "when the field is omitted it defaults to `NONE`. New students
    begin with `enrollment_status` `ENROLLED`" and "The suspension-day ledger
    behind `cumulative_suspension_days` starts at zero".

    Design: Corner/entities/student_creation_applies_defaults
    """
    payload = create_student_payload(
        full_name="Stu Def", date_of_birth="2010-05-01T00:00:00Z",
        grade_level=9, demographic_group="ASIAN", guardian_id="gd1")
    assert "disability_status" not in payload
    created = validate_success(api.create_student(payload, REF), 201)
    assert_student(created)

    fetched = validate_success(api.get_student(created["id"], CLS), 200)
    assert fetched["disability_status"] == "NONE", (
        f"omitted disability_status must default to NONE, got {fetched['disability_status']!r}")
    assert fetched["enrollment_status"] == "ENROLLED"
    assert fetched["cumulative_suspension_days"] == 0
    assert fetched["id"] == created["id"]


def test_student_missing_required_field_returns_invalid_request(api):
    """PRD §2.9: "Required fields are present, enum members are valid, and
    numeric ranges hold (grade 6 through 12, severity 1 through 4, band bounds
    with the low end at least zero and the high end at most ten and the low end
    no greater than the high end, hearing end strictly after start, placement
    planned end on or after start) — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/student_missing_required_field_returns_invalid_request
    """
    payload = {
        "date_of_birth": "2010-05-01T00:00:00Z",
        "grade_level": 9,
        "demographic_group": "ASIAN",
        "guardian_id": "gd1",
    }  # full_name omitted
    res = api.create_student(payload, REF)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(api.list_students(REF))
    assert meta["total_count"] == 0, f"no student row may persist, got {meta['total_count']}"
    assert data == []


def test_student_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "the federal-style reporting group `demographic_group` — one
    of `ASIAN`, `BLACK`, `HISPANIC`, `WHITE`, `MULTIRACIAL`, or `OTHER`".
    PRD §2.9: "Required fields are present, enum members are valid, and numeric
    ranges hold ... — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/student_invalid_enum_returns_invalid_request
    """
    payload = create_student_payload(
        full_name="Stu Enum", demographic_group="MARTIAN", guardian_id="gd1")
    res = api.create_student(payload, REF)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_student_grade_out_of_range_returns_invalid_request(api):
    """PRD §3.1: "A district enrolls a student by supplying `full_name`,
    `date_of_birth` (recorded as a date at midnight UTC), `grade_level` as an
    integer from 6 through 12".
    PRD §2.9: "numeric ranges hold (grade 6 through 12, ...) — otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/student_grade_out_of_range_returns_invalid_request
    """
    payload = create_student_payload(
        full_name="Stu Grade", date_of_birth="2012-05-01T00:00:00Z",
        grade_level=5, demographic_group="WHITE", guardian_id="gd2")
    res = api.create_student(payload, REF)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_student_computed_field_input_ignored(api):
    """PRD §3.1: "The suspension-day ledger behind `cumulative_suspension_days`
    starts at zero".
    PRD §2.7: "Its value is defined, at any moment, as the sum of
    `sanction_days_final` over exactly the student's cases whose status is
    `CONFIRMED` or `CLOSED`."

    Design: Corner/entities/student_computed_field_input_ignored
    """
    payload = create_student_payload(
        full_name="Stu Comp", demographic_group="BLACK", guardian_id="gd3")
    payload["cumulative_suspension_days"] = 99  # client-supplied computed field
    created = validate_success(api.create_student(payload, REF), 201)

    fetched = validate_success(api.get_student(created["id"], CLS), 200)
    assert fetched["cumulative_suspension_days"] == 0, (
        "server must compute the ledger from cases (none exist), ignoring the "
        f"client-supplied 99; got {fetched['cumulative_suspension_days']}")


def test_student_retrieval_matches_created_data(api):
    """PRD §3.1: "A district enrolls a student by supplying `full_name`,
    `date_of_birth` (recorded as a date at midnight UTC), `grade_level` as an
    integer from 6 through 12, the federal-style reporting group
    `demographic_group` ... and an opaque `guardian_id` identifying the primary
    parent or guardian."

    Design: Corner/entities/student_retrieval_matches_created_data
    """
    payload = create_student_payload(
        full_name="Stu Read", date_of_birth="2010-07-01T00:00:00Z",
        grade_level=8, demographic_group="HISPANIC", guardian_id="gd4",
        disability_status="SECTION_504")
    created = validate_success(api.create_student(payload, ADMIN), 201)
    assert_student(created)

    fetched = validate_success(api.get_student(created["id"], ADMIN), 200)
    assert fetched["full_name"] == "Stu Read"
    assert fetched["grade_level"] == 8
    assert fetched["demographic_group"] == "HISPANIC"
    assert fetched["disability_status"] == "SECTION_504"
    assert fetched["guardian_id"] == "gd4"


def test_students_list_pagination_and_filter(api):
    """PRD §3.1: "The roster can be listed with optional filters on
    `demographic_group`, `disability_status`, and `enrollment_status`".
    PRD §2.3: "The `meta` object of list responses carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/students_list_pagination_and_filter
    """
    validate_success(api.create_student(create_student_payload(
        full_name="P One", date_of_birth="2010-01-01T00:00:00Z",
        demographic_group="BLACK", guardian_id="gp1"), REF), 201)
    validate_success(api.create_student(create_student_payload(
        full_name="P Two", date_of_birth="2010-01-02T00:00:00Z",
        demographic_group="BLACK", guardian_id="gp2"), REF), 201)
    validate_success(api.create_student(create_student_payload(
        full_name="P Three", date_of_birth="2010-01-03T00:00:00Z",
        demographic_group="WHITE", guardian_id="gp3"), REF), 201)

    res1 = api.list_students(ADMIN, params={"demographic_group": "BLACK",
                                            "limit": 1, "offset": 0})
    body1 = res1.json()
    data1, meta1 = validate_paginated(res1)
    assert body1["response_type"] == "array"
    assert isinstance(body1["meta"]["api_request_id"], str)
    assert len(data1) == 1
    assert meta1["total_count"] == 2, (
        f"filter applies before pagination: total_count must be 2, got {meta1['total_count']}")
    assert meta1["has_more"] is True
    assert data1[0]["demographic_group"] == "BLACK"

    data2, meta2 = validate_paginated(api.list_students(
        ADMIN, params={"demographic_group": "BLACK", "limit": 1, "offset": 1}))
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert data2[0]["id"] != data1[0]["id"], "pages must return different students"

    all_black_ids = {data1[0]["id"], data2[0]["id"]}
    assert all(
        row["demographic_group"] == "BLACK" for row in (data1 + data2)
    ), "the WHITE student must appear on neither filtered page"
    assert len(all_black_ids) == 2
