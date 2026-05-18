"""Auth headers, response envelope, RBAC and pagination contracts.

PRD §2.1, §2.2, §2.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_borrower_payload,
    create_platform_payload,
    create_platform,
    make_borrower_headers,
    setup_approved_borrower,
    setup_open_listing,
    setup_platform_with_officer,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "Every request to the API MUST carry two headers:
        X-User-ID identifying the calling principal, and X-User-Role
        identifying the role the principal is acting as. Missing or
        malformed headers yield ERR_MISSING_USER_CONTEXT with HTTP
        400."

        Claim: omitting X-User-ID -> ERR_MISSING_USER_CONTEXT, 400.
        """
        # Only X-User-Role; X-User-ID missing.
        resp = api.create_platform(
            create_platform_payload(),
            {"X-User-Role": "PlatformOperator"},
        )
        validate_error(resp, "ERR_MISSING_USER_CONTEXT")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: same sentence as above — Missing or malformed
        headers yield ERR_MISSING_USER_CONTEXT with HTTP 400.

        Claim: omitting X-User-Role -> ERR_MISSING_USER_CONTEXT, 400.
        """
        resp = api.create_platform(
            create_platform_payload(),
            {"X-User-ID": "op-no-role-1"},
        )
        validate_error(resp, "ERR_MISSING_USER_CONTEXT")

    def test_both_headers_missing(self, api):
        """PRD §2.1: same sentence — Missing or malformed headers yield
        ERR_MISSING_USER_CONTEXT with HTTP 400."""
        resp = api.create_platform(create_platform_payload(), {})
        validate_error(resp, "ERR_MISSING_USER_CONTEXT")

    def test_role_not_authorized_returns_forbidden(self, api):
        """PRD §2.1: "A well-formed header pair whose role is not
        authorized for the endpoint yields ERR_FORBIDDEN_FOR_ROLE with
        HTTP 403."

        Claim: a non-operator role on POST /platforms (PlatformOperator
        only per PRD §4) -> ERR_FORBIDDEN_FOR_ROLE, 403.
        """
        # ComplianceOfficer is not authorized to create a platform.
        resp = api.create_platform(
            create_platform_payload(),
            build_user_headers("officer-x", "ComplianceOfficer"),
        )
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_response_envelope_keys(
        self, api, platform_operator_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta { api_request_id, api_request_timestamp },
        response_type, data.

        Claim: a successful POST returns meta with api_request_id
        starting "req_" and api_request_timestamp, response_type, and
        data.
        """
        resp = api.create_platform(
            create_platform_payload(),
            platform_operator_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and isinstance(body["meta"], dict)
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            f"PRD §2.2: 'starts with req_'; got "
            f"{meta['api_request_id']!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_error_response_envelope_keys(self, api):
        """PRD §2.2: error responses carry meta with api_request_id +
        api_request_timestamp, response_type='error', data with
        error_id and message."""
        resp = api.create_platform(create_platform_payload(), {})
        body = resp.json()
        assert isinstance(body.get("meta"), dict)
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body.get("response_type") == "error"
        data = body.get("data") or {}
        assert isinstance(data.get("error_id"), str)
        assert isinstance(data.get("message"), str)


# ===========================================================================
# Path resolution — PRD §2.6
# ===========================================================================
class TestPathResolution:

    def test_non_existent_platform_yields_not_found(
        self, api, platform_operator_headers,
    ):
        """PRD §2.6: "Any path component that fails to resolve yields
        ERR_NOT_FOUND with HTTP 404 at the first failing component."

        Claim: GET a platform that does not exist -> ERR_NOT_FOUND."""
        resp = api.get_platform(
            NON_EXISTENT_UUID, platform_operator_headers,
        )
        validate_error(resp, "ERR_NOT_FOUND")

    def test_non_existent_borrower_under_real_platform(
        self, api, platform_operator_headers,
    ):
        """PRD §2.6: nested resource resolution is left-to-right; a
        missing child id returns ERR_NOT_FOUND."""
        platform, _ = setup_platform_with_officer()
        resp = api.get_borrower(
            platform["id"], NON_EXISTENT_UUID,
            platform_operator_headers,
        )
        validate_error(resp, "ERR_NOT_FOUND")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_meta_carries_pagination_fields(
        self, api, platform_operator_headers,
    ):
        """PRD §2.3: "The meta block of a list response carries limit,
        offset, total_count, and has_more."

        Claim: list listings under a platform — meta includes the four
        pagination fields.
        """
        platform, officer, borrower, _ = setup_open_listing()
        resp = api.list_listings(
            platform["id"], platform_operator_headers,
        )
        data, meta = validate_paginated(resp)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing {k}"

    def test_default_limit_is_ten(self, api, platform_operator_headers):
        """PRD §2.3: "limit defaults to 10".

        Claim: a list endpoint without explicit limit returns meta.limit
        == 10.
        """
        platform, _ = setup_platform_with_officer()
        resp = api.list_listings(
            platform["id"], platform_operator_headers,
        )
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"PRD §2.3: 'limit defaults to 10'; got {meta['limit']}"
        )

    def test_limit_above_maximum_rejected(
        self, api, platform_operator_headers,
    ):
        """PRD §2.3: "a maximum of 100 ... values outside them yield
        ERR_INVALID_REQUEST".

        Claim: limit=101 -> ERR_INVALID_REQUEST.
        """
        platform, _ = setup_platform_with_officer()
        resp = api.list_listings(
            platform["id"], platform_operator_headers,
            params={"limit": 101},
        )
        validate_error(resp, "ERR_INVALID_REQUEST")

    def test_limit_below_minimum_rejected(
        self, api, platform_operator_headers,
    ):
        """PRD §2.3: "a minimum of 1 ... values outside them yield
        ERR_INVALID_REQUEST".

        Claim: limit=0 -> ERR_INVALID_REQUEST.
        """
        platform, _ = setup_platform_with_officer()
        resp = api.list_listings(
            platform["id"], platform_operator_headers,
            params={"limit": 0},
        )
        validate_error(resp, "ERR_INVALID_REQUEST")

    def test_offset_negative_rejected(
        self, api, platform_operator_headers,
    ):
        """PRD §2.3: "offset defaults to 0 with a minimum of 0 ...
        values outside them yield ERR_INVALID_REQUEST".

        Claim: offset=-1 -> ERR_INVALID_REQUEST.
        """
        platform, _ = setup_platform_with_officer()
        resp = api.list_listings(
            platform["id"], platform_operator_headers,
            params={"offset": -1},
        )
        validate_error(resp, "ERR_INVALID_REQUEST")
