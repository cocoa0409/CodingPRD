"""Role-based access control, authentication, the auth-before-state priority pair,
input validation, pagination bounds, append-only immutability, and the response
envelope shape."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, fixtures as fx,
    is_valid_uuid, assert_compliance_check_shape, make_case_manager_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]
CLERK = TEST_USERS["attendance_clerk_headers"]


def test_clerk_unauthorized_beats_invalid_state(api):
    """PRD §2.9: "1. Authentication ... 2. Authorization — the role is permitted for the
    operation per §2.1, else `ERR_UNAUTHORIZED` (403). ... 7. State admissibility — the
    target resource is in a state that admits the requested transition."

    Design: Difficulty/priority_pair_validation_conflict/clerk_transition_unauthorized_beats_invalid_state
    """
    school, student, case = fx.make_school_student_case(api)  # OPEN case
    # An AttendanceClerk may not transition cases, AND OPEN->CLOSED is itself inadmissible.
    res = api.transition_case(case["id"], {"to_status": "CLOSED"}, CLERK)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_authorized_actor_reaches_state_check_for_same_transition(api):
    """PRD §3.9: "a case in `MONITORING` or `RESOLVED` may be moved to the terminal
    `CLOSED` ... either lingering obligation blocks closure with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/clerk_transition_unauthorized_beats_invalid_state
    """
    school, student, case = fx.make_school_student_case(api)  # OPEN case
    # Administrator passes auth (p2), so the same OPEN->CLOSED now fails the state check (p7).
    res = api.transition_case(case["id"], {"to_status": "CLOSED"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_clerk_cannot_open_case(api):
    """PRD §2.1: "`CaseManager` owns the truancy-case workflow: opening and assigning
    cases ... When the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/clerk_cannot_open_case
    """
    school = fx.make_school(api)
    student = fx.make_student(api, school["id"], grade_level=9)
    res = api.create_case({"student_id": student["id"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_casemanager_cannot_file_citation(api):
    """PRD §2.1: "`CourtOfficer` handles court escalation: filing citations, scheduling
    hearings, and recording dispositions. ... the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/casemanager_cannot_file_citation
    """
    school, officer, student, case = fx.drive_case_to_court_referred(api)
    manager = fx.make_staff(api, school["id"], role_type="CASE_MANAGER", full_name="Rb2 Mgr")
    res = api.create_court_citation(
        case["id"],
        {"courtroom_id": "CR-3", "hearing_start": "2026-10-01T09:00:00Z", "hearing_end": "2026-10-01T10:00:00Z"},
        make_case_manager_headers(manager["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_schools_missing_auth_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/schools_missing_auth_unauthenticated
    """
    res = api.create_school({"name": "NoAuth School"}, {})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_create_student_missing_required_field(api):
    """PRD §2.9: "3. Body well-formedness — required fields present, scalar types correct,
    pagination in range ... else `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_student_missing_required_field
    """
    school = fx.make_school(api)
    res = api.create_student({"school_id": school["id"], "full_name": "No Grade"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_create_staff_invalid_role_enum(api):
    """PRD §2.9: "4. Enum membership — every enum-typed input (`role_type`, a resource
    `status`, `service_type`, a compliance `result`, `to_status`, `to_tier`) carries a
    declared member, else `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/create_staff_invalid_role_enum
    """
    school = fx.make_school(api)
    res = api.create_staff(
        {"school_id": school["id"], "full_name": "Bad Role", "role_type": "PRINCIPAL"}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_student_unknown_school_returns_404(api):
    """PRD §2.5: "the server validates them from left to right and rejects the request
    with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing
    resource."

    Design: Corner/entities/create_student_unknown_school_returns_404
    """
    res = api.create_student(
        {"school_id": "00000000-0000-0000-0000-000000000000", "full_name": "Orphan", "grade_level": 9}, ADMIN
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_students_pagination_invalid(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. ... A `limit` or `offset` outside its
    permitted bounds is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/entities/list_students_pagination_invalid
    """
    school = fx.make_school(api)
    res = api.list_school_students(school["id"], ADMIN, params={"limit": 0})
    validate_error(res, ApiErrorId.ERR_PAGINATION_INVALID.value)


def test_compliance_check_is_immutable_event(api):
    """PRD §2.4: "`ComplianceCheck` is the sole exception. It is an append-only monitoring
    event and carries only `id` and `created_at`; it has neither `updated_at` nor
    `version`, and it is never mutated after creation."

    Design: Corner/entities/compliance_check_is_immutable_event
    """
    school, student, case = fx.make_school_student_case(api)
    res = api.create_compliance_check(case["id"], {"check_date": "2026-09-15", "result": "COMPLIANT"}, ADMIN)
    check = validate_success(res, 201)
    assert_compliance_check_shape(check)


def test_envelope_object_shape_on_create(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources. ... The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."

    Design: Corner/cross_cutting/envelope_object_shape_on_create
    """
    res = api.create_school({"name": "Env2 School"}, ADMIN)
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_valid_uuid(body["data"]["id"])
