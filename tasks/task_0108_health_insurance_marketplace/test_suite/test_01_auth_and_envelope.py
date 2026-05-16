"""Auth, RBAC, response envelope, pagination, and NotFound.

Cross-cutting checks defined in PRD §2.1 (auth/role), §2.2 (envelope),
§2.3 (pagination), §2.5 (nested resource resolution), §3.9 (precedence).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_application_payload,
    is_iso8601_timestamp,
    setup_benchmark_silver_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED; a request whose X-User-Role is not
        authorized for the operation (per the §4 endpoint table) is
        rejected with ERR_FORBIDDEN."

        Claim: a POST with neither header set returns ERR_AUTH_REQUIRED.
        """
        res = api.create_application(create_application_payload(),
                                     headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED; a request whose X-User-Role is not
        authorized for the operation (per the §4 endpoint table) is
        rejected with ERR_FORBIDDEN."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_application(
            create_application_payload(),
            headers={"X-User-Role": "Applicant"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED; a request whose X-User-Role is not
        authorized for the operation (per the §4 endpoint table) is
        rejected with ERR_FORBIDDEN."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_application(
            create_application_payload(),
            headers={"X-User-ID": "applicant-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 RBAC — role not authorized
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "a request whose X-User-Role is not authorized for the
    operation (per the §4 endpoint table) is rejected with ERR_FORBIDDEN.\""""

    def test_applicant_cannot_create_insurer(self, api):
        """PRD §4 endpoint table: POST /insurers is restricted to
        MarketplaceAdmin.

        PRD §2.1: "a request whose X-User-Role is not authorized for
        the operation (per the §4 endpoint table) is rejected with ERR_FORBIDDEN."
        """
        from test_helpers import create_insurer_payload
        res = api.create_insurer(
            create_insurer_payload(),
            build_user_headers("applicant-x", "Applicant"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_applicant_cannot_advance_clock(self, api):
        """PRD §4 endpoint table: POST /_clock/advance is restricted to
        MarketplaceAdmin.

        PRD §2.1: "a request whose X-User-Role is not authorized for
        the operation (per the §4 endpoint table) is rejected with ERR_FORBIDDEN."
        """
        from test_helpers import clock_advance_payload, iso_offset
        res = api.clock_advance(
            clock_advance_payload(to_timestamp=iso_offset(days=1)),
            build_user_headers("applicant-x", "Applicant"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_marketplace_admin_cannot_create_application(self, api):
        """PRD §4 endpoint table: POST /applications is restricted to
        Applicant.
        """
        res = api.create_application(
            create_application_payload(),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_customer_service_cannot_approve_application(self, api):
        """PRD §4 endpoint table: POST /applications/{id}/approve is
        restricted to MarketplaceAdmin.
        """
        res = api.approve_application(
            "00000000-0000-0000-0000-000000000000",
            TEST_USERS["customer_service_headers"],
        )
        # ERR_FORBIDDEN is the role check (priority 2); existence comes
        # later (priority 3). PRD §3.9: role authorization "before any
        # path parameter is dereferenced".
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success responses follow a standard envelope with
    meta.api_request_id, meta.api_request_timestamp, response_type,
    data."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."
        """
        from test_helpers import create_application
        application = create_application()
        # Re-fetch through a successful read response to inspect envelope.
        from test_helpers import make_applicant_headers
        resp = api.get_application(
            application["id"],
            make_applicant_headers(application["_applicant_id"]),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(
            body["meta"]["api_request_timestamp"],
        )
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format."
        """
        resp = api.get_application(NON_EXISTENT_UUID,
                                   TEST_USERS["admin_headers"])
        assert 400 <= resp.status_code < 500
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert isinstance(body["data"].get("error_id"), str)
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: "The default limit is 10 results per page, the minimum
    is 1, and the maximum is 100; a request that asks for more than 100
    results is bounded back to 100. The default offset is 0.\""""

    def test_default_limit_in_meta(self, api):
        """PRD §2.3: "The response meta object echoes the effective
        limit and offset, the unfiltered total_count, and a boolean
        has_more indicating whether further pages exist."
        """
        data, meta = validate_paginated(api.list_applications(
            TEST_USERS["admin_headers"],
        ))
        assert meta.get("limit") == PAGINATION_DEFAULT_LIMIT
        assert meta.get("offset") == 0
        assert isinstance(meta.get("total_count"), int)
        assert isinstance(meta.get("has_more"), bool)

    def test_limit_capped_at_100(self, api):
        """PRD §2.3: "a request that asks for more than 100 results is
        bounded back to 100."
        """
        data, meta = validate_paginated(api.list_applications(
            TEST_USERS["admin_headers"], params={"limit": 500},
        ))
        assert meta["limit"] == 100


# ===========================================================================
# §3.9 ERR_NOT_FOUND — path parameter dereference
# ===========================================================================
class TestNotFound:
    """PRD §3.9: "Path-parameter existence is checked next, left-to-right,
    and an unresolved id raises ERR_NOT_FOUND."""

    def test_get_application_not_found(self, api):
        """PRD §3.9: unresolved id at the leftmost position →
        ERR_NOT_FOUND.
        """
        res = api.get_application(NON_EXISTENT_UUID,
                                  TEST_USERS["admin_headers"])
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_enrollment_not_found(self, api):
        res = api.get_enrollment(NON_EXISTENT_UUID,
                                 TEST_USERS["admin_headers"])
        validate_error(res, "ERR_NOT_FOUND")

    def test_nested_member_not_found_when_parent_resolves(self, api):
        """PRD §2.5: "Once both ancestors resolve, the server confirms
        that the named member_id actually belongs to that application;
        a member belonging to a different application is reported as
        ERR_NOT_FOUND."

        Claim: when the parent application resolves but the inner
        member id is bogus, the server returns ERR_NOT_FOUND (not a
        permission error).
        """
        from test_helpers import create_application
        application = create_application()
        from test_helpers import make_applicant_headers
        res = api.create_income_record(
            application["id"], NON_EXISTENT_UUID,
            {"source_type": "WAGES", "amount_cents": 1000,
             "effective_date": "2026-01-01"},
            make_applicant_headers(application["_applicant_id"]),
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_nested_parent_id_unresolved_returns_not_found(self, api):
        """PRD §2.5: "Path parameters are validated left to right. Given
        a URL of the form /applications/{id}/household-members/{member_id}
        /income-records, the server first resolves the application id;
        if that fails, the response is ERR_NOT_FOUND and the inner
        member_id is never inspected."
        """
        res = api.create_income_record(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            {"source_type": "WAGES", "amount_cents": 1000,
             "effective_date": "2026-01-01"},
            TEST_USERS["applicant_fallback_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
