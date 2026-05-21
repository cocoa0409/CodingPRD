"""Authentication, RBAC, response envelope, pagination — PRD §2.1–§2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_veteran,
    create_veteran_payload,
    make_veteran_headers,
    setup_veteran_with_granted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or X-User-Role is not
        one of the five recognized values, the request is rejected with
        ERR_UNAUTHENTICATED."
        """
        resp = api.create_veteran(
            create_veteran_payload(),
            {"X-User-Role": "VAClerk"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or X-User-Role is not
        one of the five recognized values, the request is rejected with
        ERR_UNAUTHENTICATED."
        """
        resp = api.create_veteran(
            create_veteran_payload(),
            {"X-User-ID": "some-user"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "The value of X-User-Role MUST be exactly one of
        Veteran, VAClerk, Rater, Counselor, or PlatformAdmin."
        """
        resp = api.create_veteran(
            create_veteran_payload(),
            build_user_headers("some-user", "Hacker"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_role_unauthorized_for_endpoint_returns_forbidden(self, api):
        """PRD §2.1: "If the headers are well-formed but the role is
        not authorized to invoke the requested endpoint as defined in
        §4, the request is rejected with ERR_FORBIDDEN."

        Counselor is NOT in the POST /schools authorized list (only
        PlatformAdmin per PRD §4).
        """
        resp = api.create_school(
            {
                "name": "Test U",
                "facility_code": "ABCD1234",
                "program_type": "PUBLIC_IN_STATE",
                "yellow_ribbon_enrolled": False,
                "zip_bah_code": "10001",
            },
            TEST_USERS["counselor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestPathExistence:

    def test_veteran_not_found_returns_err_not_found(self, api):
        """PRD §2.7: "Path parameters are validated left-to-right: when
        an outer id does not resolve to an extant row, the response is
        ERR_NOT_FOUND immediately without evaluating inner segments."
        """
        resp = api.get_veteran(
            NON_EXISTENT_UUID,
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_enrollment_not_found_returns_err_not_found(self, api):
        """PRD §2.7: "Path parameters are validated left-to-right: when
        an outer id does not resolve to an extant row, the response is
        ERR_NOT_FOUND immediately without evaluating inner segments."
        """
        resp = api.get_enrollment(
            NON_EXISTENT_UUID,
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_unknown_veteran_id_fk_in_claim_returns_reference_not_found(
        self, api,
    ):
        """PRD §2.7: "When an inner segment's foreign key in the body
        fails to resolve — for example, a request that supplies a
        veteran_id, school_id, enrollment_id, or original_claim_id that
        points to nothing — the response is ERR_REFERENCE_NOT_FOUND."
        """
        resp = api.create_claim(
            {
                "veteran_id": NON_EXISTENT_UUID,
                "condition_code": "5237_lumbar",
                "claim_type": "ORIGINAL",
                "proposed_rating": 30,
            },
            TEST_USERS["va_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


class TestResponseEnvelope:

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with meta (api_request_id, api_request_timestamp),
        response_type, and data.
        """
        resp = api.create_veteran(
            create_veteran_payload(),
            TEST_USERS["va_clerk_headers"],
        )
        validate_success(resp, expected_status=201)
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            f"PRD §2.2: api_request_id starts with 'req_', "
            f"got {meta['api_request_id']!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body["response_type"] == "object"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with response_type=='error' and
        data containing error_id and message.
        """
        resp = api.get_veteran(
            NON_EXISTENT_UUID,
            TEST_USERS["platform_admin_headers"],
        )
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "error_id" in body.get("data", {})
        assert isinstance(body["data"].get("message"), str)


class TestPagination:

    def test_default_limit_is_ten(self, api):
        """PRD §2.3: "The limit parameter defaults to 10 when omitted"."""
        vet = setup_veteran_with_granted_claim(granted_rating=10)
        resp = api.list_claims(
            vet["id"], make_veteran_headers(vet["id"]),
        )
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"PRD §2.3 default limit must be 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0, (
            f"PRD §2.3 default offset must be 0, got {meta['offset']}"
        )

    def test_paginated_response_carries_meta_fields(self, api):
        """PRD §2.3: "The meta block of every list response carries
        limit, offset, total_count (the total number of rows matching
        the filter before pagination), and has_more (true when
        offset + limit < total_count)."
        """
        vet = setup_veteran_with_granted_claim(granted_rating=10)
        resp = api.list_claims(
            vet["id"], make_veteran_headers(vet["id"]),
            params={"limit": 5, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 5
        assert meta["offset"] == 0
        # Single granted claim -> total_count == 1 and has_more is False.
        assert meta["total_count"] >= 1
        assert isinstance(meta["has_more"], bool)
        assert isinstance(data, list)
