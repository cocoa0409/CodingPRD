"""Role-based access control: authentication and endpoint authorization."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_employee,
    make_employee_headers,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through a set of mandatory HTTP headers. Each request must include
        `X-User-ID` to identify the acting user and `X-User-Role` to specify
        their operational capacity. The system recognizes five distinct roles:
        `HRAdmin`, `HRBusinessPartner`, `TalentManager`, `Manager`, and
        `Employee`. Failure to provide valid, recognized headers will result in
        an `ERR_UNAUTHENTICATED` error (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_employees(None)  # headers stripped for this call
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestAuthorization:
    def test_employee_cannot_create_critical_role(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role: an
        attempt to perform an action outside of the caller's designated role is
        rejected with an `ERR_UNAUTHORIZED` error (HTTP 403)."
        PRD §3.2: "An `HRBusinessPartner` identifies a **CriticalRole** by
        supplying its `role_title`, owning `department`, `criticality_tier`
        (`TIER_1`, `TIER_2`, or `TIER_3` — later used as the diversity weight),
        and `assessment_method` (`WEIGHTED` or `COVERAGE`)"

        Design: Corner/rbac/employee_cannot_create_critical_role
        """
        caller = setup_employee(employee_code="E120", full_name="Erin Nope",
                                job_level=4, hire_date="2023-06-01")
        resp = api.create_critical_role({
            "role_title": "Nope Role",
            "department": "ENG",
            "criticality_tier": "TIER_3",
            "assessment_method": "WEIGHTED",
        }, make_employee_headers(caller["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
