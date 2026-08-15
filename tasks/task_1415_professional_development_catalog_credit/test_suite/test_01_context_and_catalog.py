"""Request context, role gating, and catalog/employee resource basics."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, assert_employee, is_valid_uuid,
    make_teacher_headers, validate_error, validate_paginated, validate_success,
    make_building, make_teacher,
)
from test_helpers.factories import create_course_payload, create_employee_payload


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system
    does not declare, is rejected with `ERR_MISSING_CONTEXT` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    res = api.get_section(NON_EXISTENT_UUID, headers={})
    validate_error(res, "ERR_MISSING_CONTEXT", expected_status=400)


def test_create_course_as_teacher_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted on
    the targeted endpoint — including the entity-backed kind check described
    below — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /pd/courses is authorized for PDCoordinator only.

    Design: Corner/validations/create_course_as_teacher_forbidden
    """
    building = make_building()
    teacher = make_teacher(building["id"])
    res = api.create_course(
        create_course_payload(course_code="RB-1", title="Forbidden",
                              delivery_mode="VIRTUAL", clock_hours=5),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_employee_creation_defaults_and_system_fields(api):
    """PRD §3.9: "The employee's `current_lane` starts equal to their `base_lane`
    at hire and is bumped only by advancement; their
    `last_advancement_fiscal_year` is null until the first advancement occurs."
    PRD §3.7: "An employee's `compliance_standing` is `COMPLIANT` by default".
    PRD §3.9: "it is the sum of `district_credit` over the employee's `AWARDED`
    transcript entries that count toward the lane, minus 12.0 for each completed
    lane advancement."
    PRD §2.5: "Every primary resource carries `id` (a server-minted UUID with no
    type prefix), `created_at` and `updated_at` ... and `version` (an integer
    starting at its initial value and incrementing on every mutation of the
    resource)."
    PRD §3.1: an employee-targeted write fails on a non-`ACTIVE` employee, so the
    initial status is `ACTIVE`.

    Design: Corner/entities/employee_creation_defaults_and_system_fields
    """
    building = make_building()
    res = api.create_employee(
        create_employee_payload(building["id"], full_name="New Hire",
                                email="nh@x.com", employee_kind="TEACHER",
                                base_lane="MA15"),
        TEST_USERS["coordinator_headers"])
    emp = validate_success(res, 201)
    assert_employee(emp)
    assert emp["status"] == "ACTIVE"
    assert emp["current_lane"] == "MA15", "current_lane starts equal to base_lane"
    assert emp["lane_credit_balance"] == pytest.approx(0.0)
    assert emp["compliance_standing"] == "COMPLIANT"
    assert emp["last_advancement_fiscal_year"] is None
    assert emp["version"] == 1


def test_building_create_client_id_input_ignored(api):
    """PRD §2.5: "Every primary resource carries `id` (a server-minted UUID with
    no type prefix), `created_at` and `updated_at` (ISO 8601 UTC timestamps with
    three fractional digits), and `version` (an integer starting at its initial
    value and incrementing on every mutation of the resource)."

    Design: Corner/entities/building_create_client_id_input_ignored
    """
    client_id = "99999999-9999-4999-8999-999999999999"
    res = api.create_building(
        {"name": "Ignored Fields", "building_code": "IF1",
         "id": client_id, "version": 42},
        TEST_USERS["coordinator_headers"])
    building = validate_success(res, 201)
    assert building["id"] != client_id, "client-supplied id must be ignored"
    assert is_valid_uuid(building["id"])
    assert building["version"] == 1, "client-supplied version 42 must be ignored"


def test_course_missing_required_returns_invalid_request(api):
    """PRD §3.2: "A `Course` carries a unique `course_code`, a `title`, a
    `delivery_mode` of `IN_PERSON`, `VIRTUAL`, or `HYBRID`, and a positive
    `clock_hours` value."
    PRD §2.10 step 4: "Request shape — required fields present, types, enum
    membership, ranges, and datetime formats valid ... otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/course_missing_required_returns_invalid_request
    """
    res = api.create_course(
        {"course_code": "BAD-1", "title": "No Hours", "delivery_mode": "VIRTUAL"},
        TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_course_invalid_enum_rejected(api):
    """PRD §3.2: "a `delivery_mode` of `IN_PERSON`, `VIRTUAL`, or `HYBRID`".
    PRD §2.10 step 4: "Request shape — required fields present, types, enum
    membership, ranges, and datetime formats valid ... otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/course_invalid_enum_rejected
    """
    res = api.create_course(
        {"course_code": "BAD-2", "title": "Bad Enum",
         "delivery_mode": "SMOKE_SIGNAL", "clock_hours": 5},
        TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_section_get_not_found_returns_404(api):
    """PRD §2.9: "Each path parameter's existence is confirmed in order, and the
    first identifier that does not correspond to an existing resource terminates
    the request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/section_get_not_found_returns_404
    """
    res = api.get_section(NON_EXISTENT_UUID, TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_employee_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and it is bounded below by 1 and above by 100. The
    `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses expose `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/employee_list_pagination_defaults
    """
    building = make_building()
    for i in range(11):
        make_teacher(building["id"], email=f"e{i:02d}@x.com",
                     full_name=f"E{i:02d}")

    data, meta = validate_paginated(api.list_employees(TEST_USERS["coordinator_headers"]))
    assert len(data) == 10, "default limit is 10"
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert meta["offset"] == 0

    data2, meta2 = validate_paginated(
        api.list_employees(TEST_USERS["coordinator_headers"], params={"offset": 10}))
    assert len(data2) == 1, "offset 10 reaches the 11th row"
    assert meta2["has_more"] is False
