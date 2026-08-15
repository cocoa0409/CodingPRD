"""Authentication headers, role authorization, and validation precedence
(PRD §2.1, §2.8, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_school,
    create_school_payload,
    headers_missing_user_id,
    make_teacher_headers,
    validate_error,
)


class TestUserContextHeader:
    def test_missing_x_user_id_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in
        which they act. A request in which either header is missing or malformed
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
        400)."

        Design: Corner/validations/missing_x_user_id_header_returns_400
        """
        # X-User-Role present, X-User-ID absent.
        resp = api.list_schools(headers_missing_user_id("District504Director"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        # Both headers absent.
        resp2 = api.list_schools({"Content-Type": "application/json"})
        validate_error(resp2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_invalid_role_returns_403(self, api):
        """PRD §2.1: "The system recognizes exactly five roles, spelled
        precisely as follows: `District504Director`, `Section504Coordinator`,
        `Teacher`, `SchoolPrincipal`, and `Parent`. Each operation is restricted
        to a designated set of roles (enumerated per endpoint in §4); an
        authenticated caller whose role is not permitted for the requested
        operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/schools` — "Create a school" — authorized role:
        District504Director.

        Design: Corner/validations/invalid_role_returns_403
        """
        resp = api.create_school(
            create_school_payload(school_name="X", district_code="X",
                                  current_academic_year="2026-2027"),
            make_teacher_headers("some-teacher"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_parent_cannot_create_student(self, api):
        """PRD §2.1: "Each operation is restricted to a designated set of roles
        (enumerated per endpoint in §4); an authenticated caller whose role is
        not permitted for the requested operation is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/students` — "Register a student" — authorized roles:
        Section504Coordinator, SchoolPrincipal.

        Design: Corner/roles/parent_cannot_create_student
        """
        school = create_school()
        resp = api.create_student(
            {"school_id": school["id"], "student_external_ref": "X", "full_name": "X",
             "date_of_birth": "2012-01-01T00:00:00Z", "grade_level": 8},
            TEST_USERS["parent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestValidationPrecedence:
    def test_priority_auth_before_existence(self, api):
        """PRD §2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order so the surfaced error is
        deterministic rather than an accident of implementation. The order is:

        1. Header presence and well-formedness — failures yield
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
        2. Role authorization for the endpoint — failures yield
        `ERR_UNAUTHORIZED_ROLE`.
        3. Existence of every path-templated and referenced resource — failures
        yield `ERR_NOT_FOUND` or the resource-specific 404."

        Design: Corner/validations/priority_auth_before_existence
        """
        # Unauthenticated request to a non-existent student: the header check
        # (priority 1) must surface before the existence check (priority 3).
        resp = api.get_student(NON_EXISTENT_UUID, {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400
