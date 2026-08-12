"""Authentication and role authorization (PRD §2.1, §2.6, §4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_employer,
    create_employer_payload,
    create_program_payload,
    make_employee_headers,
    setup_active_enrollment,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["benefits_admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated through a
        set of mandatory HTTP headers. ... A request that arrives without valid
        headers, or whose role value is not one of these declared role names, is
        rejected with `ERR_UNAUTHENTICATED`."
        PRD §2.6: "The `X-User-Role` and `X-User-ID` headers are present and the
        role is a declared role name; otherwise `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        res = api.create_employer(create_employer_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_employee_cannot_create_program_forbidden(self, api):
        """PRD §2.1: "Access to specific operations is further restricted by role;
        an attempt to perform an action outside of the caller's designated role is
        rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/wellness/programs` | Create a program (starts DRAFT) |
        BenefitsAdmin |" (Employee is not an authorized role)

        Design: Corner/validations/employee_cannot_create_program_forbidden
        """
        employer = create_employer()
        res = api.create_program(
            create_program_payload(employer["id"]),
            make_employee_headers("00000000-0000-4000-8000-0000000000aa"),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_platform_admin_cannot_submit_hra(self, api):
        """PRD §2.1: "Access to specific operations is further restricted by role;
        an attempt to perform an action outside of the caller's designated role is
        rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/wellness/hras` | Submit and score an HRA in one call;
        HIGH risk auto-creates a coaching referral | Employee |" (PlatformAdmin is
        not an authorized role)

        Design: Corner/rbac/platform_admin_cannot_submit_hra
        """
        ctx = setup_active_enrollment()
        res = api.create_hra(
            {"enrollment_id": ctx["enrollment"]["id"], "answers": [2] * 10},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
