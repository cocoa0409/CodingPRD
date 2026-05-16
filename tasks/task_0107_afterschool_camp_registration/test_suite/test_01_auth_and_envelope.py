"""Auth, RBAC, response envelope, pagination, and NotFound.

These tests exercise cross-cutting checks defined in PRD §2.1
(auth/role), §2.2 (envelope), §2.3 (pagination), §2.6 (NotFound),
which apply across every endpoint.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_family,
    create_family_payload,
    is_iso8601_timestamp,
    setup_family_with_primary_guardian,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers / unknown role / unauthorized role
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or blank, the request
        is rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: a POST with neither header set returns ERR_AUTH_REQUIRED.
        """
        res = api.create_family(create_family_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or blank, the request
        is rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_family(
            create_family_payload(),
            headers={"X-User-Role": "ProgramAdmin"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or blank, the request
        is rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_family(
            create_family_payload(),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_blank_user_id_rejected(self, api):
        """PRD §2.1: "If either header is missing or blank, the request
        is rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: X-User-ID set to empty string returns ERR_AUTH_REQUIRED.
        """
        res = api.create_family(
            create_family_payload(),
            headers={"X-User-ID": "", "X-User-Role": "ProgramAdmin"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


class TestRoleAuthorization:
    """PRD §2.1: "If the role on the request is not authorized for the
    endpoint being called (per the RBAC mapping summarized in §4), the
    request is rejected with ERR_FORBIDDEN and HTTP status 403.\""""

    def test_guardian_cannot_create_session(self, api):
        """PRD §4 endpoint table: POST /camp/sessions is restricted to
        ProgramAdmin.

        PRD §2.1: "If the role on the request is not authorized for
        the endpoint being called (per the RBAC mapping summarized in
        §4), the request is rejected with ERR_FORBIDDEN and HTTP
        status 403."

        Claim: a Guardian calling POST /camp/sessions returns
        ERR_FORBIDDEN.
        """
        from test_helpers import create_session_payload
        res = api.create_session(
            create_session_payload(),
            build_user_headers("some-guardian-id", "Guardian"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_guardian_cannot_grant_scholarship(self, api):
        """PRD §4 endpoint table: POST /camp/families/{family_id}/
        scholarships is restricted to ProgramAdmin.

        PRD §2.1: "If the role on the request is not authorized for
        the endpoint being called (per the RBAC mapping summarized in
        §4), the request is rejected with ERR_FORBIDDEN and HTTP
        status 403."

        Claim: a Guardian attempting to grant a scholarship returns
        ERR_FORBIDDEN.
        """
        from test_helpers import create_scholarship_payload
        family, guardian = setup_family_with_primary_guardian()
        from test_helpers import make_guardian_headers
        res = api.create_scholarship(
            family["id"],
            create_scholarship_payload(),
            make_guardian_headers(guardian["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_guardian_cannot_advance_clock(self, api):
        """PRD §4 endpoint table: POST /_clock/advance is restricted
        to ProgramAdmin.

        PRD §2.1: "If the role on the request is not authorized for
        the endpoint being called (per the RBAC mapping summarized in
        §4), the request is rejected with ERR_FORBIDDEN and HTTP
        status 403."

        Claim: a Guardian attempting to advance the clock returns
        ERR_FORBIDDEN.
        """
        from test_helpers import clock_advance_payload, iso_offset
        family, guardian = setup_family_with_primary_guardian()
        from test_helpers import make_guardian_headers
        res = api.clock_advance(
            clock_advance_payload(iso_timestamp=iso_offset(days=1)),
            make_guardian_headers(guardian["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 + §3.1 Cross-family ownership — ERR_FAMILY_MISMATCH (HTTP 403)
# ===========================================================================
class TestFamilyMismatch:
    """PRD §2.1: "Cross-family access by a Guardian is forbidden."""

    def test_guardian_cannot_read_other_family_invoice(self, api):
        """PRD §2.1: "When a Guardian attempts to operate on a Child,
        EmergencyContact, Authorization, or Enrollment that does not
        roll up to their own Family, the request is rejected with
        ERR_FAMILY_MISMATCH and HTTP status 403."

        Claim: a Guardian of family A reading family B's invoice
        returns ERR_FAMILY_MISMATCH.
        """
        from test_helpers import make_guardian_headers
        family_a, guardian_a = setup_family_with_primary_guardian()
        family_b, _ = setup_family_with_primary_guardian()
        res = api.get_family_invoice(
            family_b["id"],
            make_guardian_headers(guardian_a["id"]),
            params={"week_start": "2030-01-06"},
        )
        validate_error(res, "ERR_FAMILY_MISMATCH")


# ===========================================================================
# §2.2 Response envelope — every 2xx carries meta + response_type + data
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body.\""""

    def test_success_envelope_has_meta_response_type_data(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        PRD §2.2: "The api_request_timestamp is a server-generated ISO
        8601 UTC timestamp with three fractional digits."

        Claim: a successful POST returns meta.api_request_id starting
        with "req_", meta.api_request_timestamp as ISO 8601, and a
        data object.
        """
        res = api.create_family(
            create_family_payload(),
            TEST_USERS["admin_headers"],
        )
        body = res.json()
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(
            body["meta"]["api_request_timestamp"]
        )
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."
        PRD §2.2: "The message provides a human-readable explanation of
        what went wrong."

        Claim: an error response carries response_type=="error" and
        data.error_id + data.message.
        """
        res = api.create_family(create_family_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# §2.3 Pagination — default limit, has_more flag, total_count
# ===========================================================================
class TestPagination:
    """PRD §2.3: "All list endpoints accept two optional query
    parameters: limit and offset.\""""

    def test_default_limit_applied(self, api):
        """PRD §2.3: "The default limit is 10, the minimum is 1, and
        the maximum is 100; the default offset is 0."

        Claim: listing sessions without query params returns at most
        PAGINATION_DEFAULT_LIMIT rows.
        """
        # Seed more than the default limit so we can detect truncation.
        for _ in range(PAGINATION_DEFAULT_LIMIT + 2):
            from test_helpers import create_session
            create_session()
        data, meta = validate_paginated(
            api.list_sessions(TEST_USERS["admin_headers"]),
        )
        assert len(data) <= PAGINATION_DEFAULT_LIMIT
        assert "total_count" in meta
        assert "has_more" in meta

    def test_limit_offset_pagination(self, api):
        """PRD §2.3: "List responses additionally populate total_count
        (the unbounded count of rows matching the filter set) and
        has_more (true when more rows exist beyond the current
        window)."

        Claim: requesting limit=1 returns a single row and has_more=true
        when more rows exist.
        """
        from test_helpers import create_session
        for _ in range(3):
            create_session()
        data, meta = validate_paginated(
            api.list_sessions(
                TEST_USERS["admin_headers"], params={"limit": 1},
            ),
        )
        assert len(data) == 1
        assert meta["has_more"] is True

    def test_offset_past_end_returns_empty(self, api):
        """PRD §2.3: "List results are sorted by created_at ascending."

        Claim: requesting an offset past the total returns an empty
        page with has_more=false.
        """
        from test_helpers import create_session
        create_session()
        data, meta = validate_paginated(
            api.list_sessions(
                TEST_USERS["admin_headers"], params={"offset": 9999},
            ),
        )
        assert data == []
        assert meta["has_more"] is False


# ===========================================================================
# §2.6 NotFound — left-to-right path resolution; ERR_RESOURCE_NOT_FOUND
# ===========================================================================
class TestResourceNotFound:
    """PRD §2.6: "The first parameter that fails to resolve causes the
    request to be rejected with ERR_RESOURCE_NOT_FOUND and HTTP status
    404. This left-to-right ordering means that a request for an
    existing child under a non-existent family fails at the family
    hop, not the child hop.\""""

    def test_get_family_not_found(self, api):
        """PRD §2.6: "The first parameter that fails to resolve causes
        the request to be rejected with ERR_RESOURCE_NOT_FOUND and
        HTTP status 404."

        Claim: GET /camp/families/{non-existent} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_family(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_get_session_not_found(self, api):
        """PRD §2.6: "The first parameter that fails to resolve causes
        the request to be rejected with ERR_RESOURCE_NOT_FOUND and
        HTTP status 404."

        Claim: GET /camp/sessions/{non-existent} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_session(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_get_enrollment_not_found(self, api):
        """PRD §2.6: "The first parameter that fails to resolve causes
        the request to be rejected with ERR_RESOURCE_NOT_FOUND and
        HTTP status 404."

        Claim: GET /camp/enrollments/{non-existent} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_enrollment(
            NON_EXISTENT_UUID, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")

    def test_get_child_not_found(self, api):
        """PRD §2.6: "The first parameter that fails to resolve causes
        the request to be rejected with ERR_RESOURCE_NOT_FOUND and
        HTTP status 404."

        Claim: GET /camp/children/{non-existent} returns
        ERR_RESOURCE_NOT_FOUND.
        """
        res = api.get_child(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
        validate_error(res, "ERR_RESOURCE_NOT_FOUND")
