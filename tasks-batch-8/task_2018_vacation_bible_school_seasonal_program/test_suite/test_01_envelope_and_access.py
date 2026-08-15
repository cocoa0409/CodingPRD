"""Response envelope shape and role-based access control (PRD §2.1, §2.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_classroom_payload,
    create_family,
    create_program,
    create_volunteer,
    is_iso8601_timestamp,
    propose_assignment,
    submit_check,
    validate_error,
    validate_success,
)


class TestEnvelopeShape:
    def test_success_envelope_object_shape(self, api, program_director_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" and "The
        `response_type` is either "object" for a single resource or "array" for
        a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        program = create_program()
        resp = api.get_program(program["id"], program_director_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"], "api_request_id must be non-empty"
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == program["id"]

    def test_error_envelope_shape(self, api, program_director_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`error_id` is a unique, machine-readable
        string" and "`message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_program(NON_EXISTENT_UUID, program_director_headers)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["data"].get("error_id"), str)
        assert isinstance(body["data"].get("message"), str)
        assert body["data"]["message"].strip(), "message must be non-empty"
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthentication:
    def test_undeclared_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/request_with_undeclared_role_returns_unauthenticated
        """
        headers = build_user_headers("someone-1", "SuperUser")
        resp = api.list_programs(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_anonymous_cannot_list_programs(self, api, anonymous_headers):
        """PRD §2.1: "`Anonymous` — the unauthenticated public caller, admitted
        only to self-service intake: household self-registration and volunteer
        self-application." and "A request whose role is not listed for the
        target endpoint, or that violates an ownership rule, is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/anonymous_list_programs_forbidden
        """
        resp = api.list_programs(anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestRoleAuthorization:
    def test_parent_cannot_create_classroom(self, api):
        """PRD §2.1: "A request whose role is not listed for the target
        endpoint, or that violates an ownership rule, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." (§4 lists POST /vbs/classrooms for
        RegistrationCoordinator only.)

        Design: Corner/validations/parent_create_classroom_returns_forbidden
        """
        program = create_program()
        family = create_family()
        from test_helpers import make_parent_headers
        resp = api.create_classroom(
            create_classroom_payload(program["id"]),
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_parent_cannot_checkin_child(self, api):
        """PRD §2.1: "A request whose role is not listed for the target
        endpoint, or that violates an ownership rule, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)." PRD §2.9: "Tiers run in ascending priority
        number, and when several checks fail at once the lowest-numbered
        failure wins and produces the response." — authorization (priority 2)
        precedes existence (priority 3), so the unresolvable ids never surface.

        Design: Corner/rbac/parent_cannot_checkin_child
        """
        family = create_family()
        from test_helpers import make_parent_headers
        resp = api.check_in(
            {"child_id": NON_EXISTENT_UUID, "program_day_id": NON_EXISTENT_UUID},
            make_parent_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_parent_cross_family_child_read_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of
        the acting `Family`; ownership checks on any resource that references a
        family — a child, a registration, an accommodation plan — compare the
        resource's family reference to `X-User-ID`, and acting on another
        family's resources is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/parent_cross_family_child_read_forbidden
        """
        from test_helpers import create_child, make_parent_headers
        family_a = create_family()
        child = create_child(family_a["id"])
        family_b = create_family()
        resp = api.get_child(child["id"], make_parent_headers(family_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_volunteer_reads_own_record_ok(self, api):
        """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id`
        of the acting `Volunteer`"; PRD §3.4: "The application is born
        `APPLIED`".

        Design: Corner/rbac/volunteer_reads_own_record_ok
        """
        from test_helpers import make_volunteer_headers
        program = create_program()
        volunteer = create_volunteer(program["id"])
        resp = api.get_volunteer(volunteer["id"], make_volunteer_headers(volunteer["id"]))
        data = validate_success(resp)
        assert data["status"] == "APPLIED"

    def test_safety_officer_cannot_confirm_assignment(self, api, safety_officer_headers):
        """PRD §2.1: "`SafetyOfficer` — the child-safety reviewer owning
        screening decisions and accommodation approvals; cannot confirm role
        assignments." and "A request whose role is not listed for the target
        endpoint, or that violates an ownership rule, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/safety_officer_cannot_confirm_assignment
        """
        program = create_program()
        from test_helpers import create_classroom
        classroom = create_classroom(program["id"])
        volunteer = create_volunteer(program["id"])
        assignment = propose_assignment(volunteer["id"], classroom["id"], "ASSISTANT_TEACHER")
        resp = api.confirm_role_assignment(assignment["id"], safety_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_volunteer_coordinator_cannot_decide_screening(self, api, volunteer_coordinator_headers):
        """PRD §2.1: "`VolunteerCoordinator` — the volunteer scheduler
        confirming role assignments; cannot decide screenings." and "A request
        whose role is not listed for the target endpoint, or that violates an
        ownership rule, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/volunteer_coordinator_cannot_decide_screening
        """
        program = create_program()
        volunteer = create_volunteer(program["id"])
        check = submit_check(volunteer["id"], "BACKGROUND")
        resp = api.decide_screening_check(
            check["id"], {"decision": "CLEARED"}, volunteer_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
