"""Authentication, role permission, response envelope, and pagination
— PRD §2.1, §2.2, §2.3, §2.4, §2.6.

Universal cross-cutting rules that apply to every endpoint: missing
headers, role-permission mismatches, envelope shape, pagination
bounds, path-vs-body existence distinction.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_hiring_manager_payload,
    create_recruiter_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth / role-permission probes — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_returns_err_unauthorized(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`
        identifying the acting principal, and `X-User-Role` declaring
        the role under which the request is being made. If either
        header is absent or empty, the request is rejected with
        `ERR_UNAUTHORIZED`."

        Claim: request with neither header → ERR_UNAUTHORIZED / 401.
        """
        resp = api._request(
            "GET", f"/recruiters/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_missing_user_id_returns_err_unauthorized(self, api):
        """PRD §2.1: "If either header is absent or empty, the request
        is rejected with `ERR_UNAUTHORIZED`.\""""
        resp = api._request(
            "GET", f"/recruiters/{NON_EXISTENT_UUID}",
            headers={"X-User-Role": "Recruiter"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_missing_user_role_returns_err_unauthorized(self, api):
        """PRD §2.1: "If either header is absent or empty, the request
        is rejected with `ERR_UNAUTHORIZED`.\""""
        resp = api._request(
            "GET", f"/recruiters/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_empty_user_id_returns_err_unauthorized(self, api):
        """PRD §2.1: "If either header is absent or empty, the request
        is rejected with `ERR_UNAUTHORIZED`.\""""
        resp = api._request(
            "GET", f"/recruiters/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "", "X-User-Role": "Recruiter"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_role_not_permitted_returns_forbidden(
        self, api, payroll_operator_headers,
    ):
        """PRD §2.1: "If the headers are present but the declared role
        is not authorized for the requested endpoint (per the endpoint
        table in §4), the request is rejected with `ERR_FORBIDDEN`."

        Claim: PayrollOperator is not in /recruiters POST authorized
        list → ERR_FORBIDDEN.
        """
        resp = api.create_recruiter(
            create_recruiter_payload(), payroll_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_recruiter_cannot_create_recruiter(self, api, recruiter_headers):
        """PRD §4 endpoint table: POST /recruiters → PlatformAdmin only.

        Claim: Recruiter role attempting POST /recruiters → ERR_FORBIDDEN.
        """
        resp = api.create_recruiter(
            create_recruiter_payload(), recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_recruiter_cannot_create_hiring_manager(
        self, api, recruiter_headers,
    ):
        """PRD §4: POST /hiring-managers → PlatformAdmin.

        Claim: Recruiter attempting POST /hiring-managers → ERR_FORBIDDEN.
        """
        resp = api.create_hiring_manager(
            create_hiring_manager_payload(), recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope shape — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, platform_admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... `meta`
        ... `response_type` ... `data` ..."  PRD §2.2: "The
        `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`. The `api_request_timestamp`
        is a server-generated ISO 8601 UTC timestamp with three
        fractional digits."

        Claim: 2xx response carries meta with api_request_id starting
        with `req_` and ISO 8601 api_request_timestamp; response_type
        == "object"; data carries the resource.
        """
        payload = create_recruiter_payload()
        resp = api.create_recruiter(payload, platform_admin_headers)
        # PRD §2.7: "Endpoints that create a new persisted resource ...
        # return HTTP 201."
        assert resp.status_code == 201, (
            f"Expected 201 for recruiter create, got {resp.status_code}"
        )
        body = resp.json()
        assert "meta" in body, "envelope missing 'meta'"
        meta = body["meta"]
        assert "api_request_id" in meta, "meta missing api_request_id"
        assert str(meta["api_request_id"]).startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta, (
            "meta missing api_request_timestamp"
        )
        assert is_iso8601_timestamp(str(meta["api_request_timestamp"])), (
            f"api_request_timestamp must be ISO 8601, got "
            f"{meta['api_request_timestamp']!r}"
        )
        assert body.get("response_type") == "object", (
            f"Expected response_type=object, got {body.get('response_type')!r}"
        )
        assert "data" in body and isinstance(body["data"], dict)
        assert is_valid_uuid(str(body["data"]["id"])), (
            "envelope data should carry a UUID id"
        )

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... `data` ... `error_id` ...
        `message` ..." PRD §2.2: "The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Claim: an unauthenticated request returns the documented error
        envelope with error_id == ERR_UNAUTHORIZED and a message.
        """
        resp = api._request(
            "GET", f"/recruiters/{NON_EXISTENT_UUID}", headers={},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {})
        assert data.get("error_id") == "ERR_UNAUTHORIZED"
        assert isinstance(data.get("message"), str) and data["message"]


# ===========================================================================
# Path-vs-body existence distinction — PRD §2.6
# ===========================================================================
class TestPathVsBodyExistence:

    def test_unknown_path_id_returns_404_not_found(self, api,
                                                    platform_admin_headers):
        """PRD §2.6: "URL paths are validated left to right. For a
        path like `/requisitions/{requisition_id}/applications`, the
        server first resolves the requisition; if it does not exist,
        the response is `ERR_NOT_FOUND` and the rest of the path is
        not evaluated."

        Claim: GET on a non-existent path id → ERR_NOT_FOUND / 404.
        """
        resp = api.get_recruiter(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_default_pagination_meta_present(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "The `meta` block of a list response always
        carries `limit`, `offset`, `total_count` (the total number of
        records matching the filter ignoring pagination), and
        `has_more` (a boolean that is true when
        `offset + limit < total_count`)."

        Claim: GET /requisitions returns a paginated envelope whose
        meta carries all four fields.
        """
        resp = api.list_requisitions(platform_admin_headers)
        data, meta = validate_paginated(resp)
        # PRD §2.3: defaults limit=10, offset=0.
        assert meta["limit"] == 10, (
            f"default limit must be 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0, (
            f"default offset must be 0, got {meta['offset']}"
        )
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_list_respects_explicit_limit_and_offset(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "All list endpoints accept two query parameters,
        `limit` and `offset`."

        Claim: the meta block echoes the supplied limit and offset.
        """
        resp = api.list_requisitions(
            platform_admin_headers, params={"limit": 5, "offset": 0},
        )
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 5
        assert meta["offset"] == 0
