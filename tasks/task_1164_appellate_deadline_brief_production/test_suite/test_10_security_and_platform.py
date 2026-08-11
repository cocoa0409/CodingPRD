"""Authentication, authorization exclusivity, pagination bounds, logical clock,
body FK references."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    build_user_headers, NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equal,
    create_court_payload, create_attorney_payload, create_case_payload,
    create_court, create_attorney,
    attorney_headers,
    reset_clock,
    TEST_DEFAULTS,
    CLERK, ADMIN,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, identifying the acting
        role. A request missing either header, or carrying a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        res = api.list_courts(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    def test_unrecognized_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, identifying the acting
        role. A request missing either header, or carrying a role the system
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        res = api.list_courts(headers=build_user_headers("test-wizard-1", "Wizard"))
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestRoleExclusivity:
    def test_court_clerk_cannot_create_court(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        invoke the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`CourtAdmin` — a platform administrator who registers courts
        and attorneys and drives the test clock."

        Design: Corner/rbac/court_clerk_cannot_create_court
        """
        res = api.create_court(create_court_payload(code="RB1"), CLERK)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


class TestPaginationBounds:
    def test_limit_above_max_returns_pagination_error(self, api, court_admin_headers):
        """PRD §2.3: "A request whose `limit` falls outside the range 1 through
        100 inclusive, or whose `offset` is negative, is rejected with
        `ERR_PAGINATION` (HTTP 400)."

        Design: Corner/endpoints/pagination_invalid_limit_returns_pagination_error
        """
        res = api.list_courts(court_admin_headers, params={"limit": 200})
        validate_error(res, ApiErrorId.ERR_PAGINATION.value, expected_status=400)

    def test_limit_zero_returns_pagination_error(self, api, court_admin_headers):
        """PRD §2.3: "A request whose `limit` falls outside the range 1 through
        100 inclusive, or whose `offset` is negative, is rejected with
        `ERR_PAGINATION` (HTTP 400)."

        Design: Corner/endpoints/pagination_invalid_limit_returns_pagination_error
        """
        res = api.list_courts(court_admin_headers, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_PAGINATION.value, expected_status=400)

    def test_negative_offset_returns_pagination_error(self, api, court_admin_headers):
        """PRD §2.3: "A request whose `limit` falls outside the range 1 through
        100 inclusive, or whose `offset` is negative, is rejected with
        `ERR_PAGINATION` (HTTP 400)."

        Design: Corner/endpoints/pagination_invalid_limit_returns_pagination_error
        """
        res = api.list_courts(court_admin_headers, params={"offset": -1})
        validate_error(res, ApiErrorId.ERR_PAGINATION.value, expected_status=400)


class TestLogicalClock:
    def test_clock_boots_at_default_and_accepts_override(self, api, court_admin_headers):
        """PRD §2.5: "When the server boots, the logical clock is pinned at
        2026-05-01T00:00:00Z, an instant deliberately chosen to sit at or before
        every ordinary fixture date so that an unset clock behaves as a fixed
        earliest instant instead of drifting with wall time."
        PRD §2.5: "A `CourtAdmin` may override the logical clock through the
        clock-setting capability, supplying the target instant as `to_iso8601`;
        any role may read the current value, returned as `current_utc`."

        Design: Corner/endpoints/clock_set_default_and_override
        """
        initial = validate_success(api.get_clock(court_admin_headers), 200)
        assert_instant_equal(
            initial["current_utc"], "2026-05-01T00:00:00Z",
            "server must boot with the logical clock pinned at 2026-05-01T00:00:00Z",
        )

        validate_success(
            api.set_clock({"to_iso8601": "2026-08-15T10:30:00Z"}, court_admin_headers), 200
        )
        after = validate_success(api.get_clock(court_admin_headers), 200)
        assert_instant_equal(after["current_utc"], "2026-08-15T10:30:00Z")


class TestBodyForeignKeys:
    def test_case_with_nonexistent_court_id_returns_fk_not_found(self, api):
        """PRD §2.8: "Identifiers supplied in a request body rather than the URL
        — `court_id`, `schedule_id`, `author_attorney_id`, `brief_id`,
        `basis_decision_id`, and the like — are validated the same way, and a
        body-supplied reference that does not exist yields `ERR_FK_NOT_FOUND`
        (HTTP 404)."
        PRD §3.2: "A `court_id` or `lead_attorney_id` that does not resolve
        fails with `ERR_FK_NOT_FOUND`."

        Design: Corner/validations/fk_reference_to_nonexistent_court_returns_fk_not_found
        """
        reset_clock()
        attorney = create_attorney(bar_number="BAR-FK", admitted_court_ids=[])
        res = api.create_case(
            create_case_payload(NON_EXISTENT_UUID, attorney["id"], docket_number="FK-1"),
            attorney_headers(attorney),
        )
        validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value, expected_status=404)
