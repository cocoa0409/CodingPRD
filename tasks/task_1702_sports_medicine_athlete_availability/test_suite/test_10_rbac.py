"""Role-based access control and authentication context."""
from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    create_athlete,
    create_team,
    injury_case_payload,
    set_clock,
    setup_open_case,
    validate_error,
    workload_session_payload,
)


class TestRoleDenials:
    def test_coaching_staff_cannot_create_injury_case(self, api, coaching_staff_headers):
        """PRD §2.1: "If the role is valid but not permitted for the requested
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: `POST /sports-med/injury-cases` is authorized for
        `MedicalStaff` only.

        Design: Corner/rbac/coaching_staff_cannot_create_injury_case
        """
        sc = setup_open_case()  # provides team, athlete, diagnosis code
        resp = api.create_injury_case(
            injury_case_payload(
                sc["athlete"]["id"], sc["diagnosis_code"]["id"],
                occurred_on="2026-08-01", surface="GRASS", mechanism="CONTACT",
            ),
            coaching_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_billing_staff_cannot_ingest_workload(self, api, billing_staff_headers):
        """PRD §2.1: "If the role is valid but not permitted for the requested
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: `POST /sports-med/workload-sessions` is authorized for
        `PerformanceStaff` only.

        Design: Corner/rbac/billing_staff_cannot_ingest_workload
        """
        team = create_team(
            name="ACL", sport="FOOTBALL", season_start_date="2026-07-01",
            season_end_date="2027-02-01",
        )
        athlete = create_athlete(team["id"], position="QB", enrollment_date="2026-07-01")
        set_clock("2026-07-28T00:00:00Z")
        resp = api.create_workload_session(
            workload_session_payload(
                athlete["id"], "2026-07-28", duration_minutes=60, rpe=5
            ),
            billing_staff_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestAuthenticationContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing, or if `X-User-Role` does
        not match one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_teams(ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
