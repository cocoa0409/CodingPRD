"""Authentication and authorization: missing headers, role denial, and the
PlatformAdmin test-driving capability (PRD §2.1, §2.6, §4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_member,
    make_member_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestAuthentication:
    def test_missing_role_header_returns_401(self, api):
        """PRD §2.1: "Every request to the API carries two headers:
        `X-User-ID` and `X-User-Role`. The role value must be exactly one of
        the following role names — `Anonymous`, `Member`, `ShopStaff`,
        `ComplianceOfficer`, `PlatformAdmin` — spelled exactly as shown. A
        request that arrives without these headers, or with malformed values,
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        set_clock()
        # X-User-ID present but X-User-Role absent.
        resp = api.list_categories(headers={"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_member_cannot_create_category(self, api):
        """PRD §4: "| POST | `/nabs/categories` | Create a category |
        PlatformAdmin, ShopStaff |"
        PRD §2.1: "A request whose role is not on the authorized list for the
        target endpoint is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/roles/member_cannot_create_category
        """
        set_clock()
        member = make_member(email="mr@x.com")
        resp = api.create_category(
            {"code": "xx", "display_name": "XX", "compliance_class": "STANDARD"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestPlatformAdminCapability:
    def test_platform_admin_drives_clock(self, api):
        """PRD §2.6: "At server startup the logical clock reads
        `2026-05-01T00:00:00Z` and never falls back to the wall clock
        thereafter. A `PlatformAdmin` may advance the clock via a dedicated
        test-driving capability that takes a `to_iso8601` timestamp; when the
        clock moves, the system evaluates every pending system-scheduled
        transition whose preconditions are now satisfied and applies them in
        dependency order."
        PRD §4: "| POST | `/nabs/_clock/set_current_utc` | Set the logical
        UTC clock | PlatformAdmin |"

        Design: Corner/roles/platform_admin_drives_clock_and_billing
        """
        resp = api.set_clock("2026-06-01T00:00:00Z", ADMIN)
        validate_success(resp, 200)
