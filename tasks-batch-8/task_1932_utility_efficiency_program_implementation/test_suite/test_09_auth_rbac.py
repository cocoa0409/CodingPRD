"""Authentication and role authorization: missing headers, wrong role on a
ProgramManager-only endpoint, and Contractor denied project approval."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contractor_payload,
    create_program_payload,
    create_proposed_project,
    get_program,
    make_contractor_headers,
    set_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD 2.1: "A request missing either header, or presenting an empty
        value for one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_programs(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_wrong_role_unauthorized(self, api, pm_headers):
        """PRD 2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
        per-endpoint role assignments appear in §4." (§4: POST
        /efficiency/programs is ProgramManager-only.)

        Design: Corner/validations/wrong_role_unauthorized
        """
        contractor = validate_success(
            api.create_contractor(create_contractor_payload(), pm_headers),
            expected_status=201,
        )
        resp = api.create_program(
            create_program_payload(code="P-U"),
            make_contractor_headers(contractor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_contractor_cannot_approve_own_project(self, api, pm_headers):
        """PRD 2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the
        per-endpoint role assignments appear in §4." (§4: POST
        /efficiency/projects/{project_id}/approve is ProgramManager-only.)

        Design: Corner/roles/contractor_cannot_approve_own_project
        """
        set_clock()
        ctx = create_proposed_project()
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(
            ctx["project"]["id"], version,
            make_contractor_headers(ctx["contractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
