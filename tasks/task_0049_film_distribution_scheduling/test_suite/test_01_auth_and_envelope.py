"""Authentication, RBAC, response envelope, pagination, path existence.

Covers PRD §2.1, §2.2, §2.3, §2.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_distributor_payload,
    create_film_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# §2.1 -- Headers must be present.
# =========================================================================
class TestMissingAuthHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: 'Every request other than GET /_meta/health must
        carry two HTTP headers: X-User-ID and X-User-Role. Either header
        missing or empty produces a 401 response with error_id
        ERR_AUTH_HEADERS_MISSING.'

        Claim: missing X-User-ID -> ERR_AUTH_HEADERS_MISSING / 401.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api._request(
            "POST", "/distributors",
            create_distributor_payload(), bad,
        )
        validate_error(res, ApiErrorId.ERR_AUTH_HEADERS_MISSING.value)

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'Every request other than GET /_meta/health must
        carry two HTTP headers: X-User-ID and X-User-Role. Either header
        missing or empty produces a 401 response with error_id
        ERR_AUTH_HEADERS_MISSING.'

        Claim: missing X-User-Role -> ERR_AUTH_HEADERS_MISSING / 401.
        """
        bad = {"X-User-ID": "admin-001"}
        res = api._request("GET", "/distributors/anything", headers=bad)
        validate_error(res, ApiErrorId.ERR_AUTH_HEADERS_MISSING.value)

    def test_empty_user_id_header(self, api):
        """PRD §2.1: 'Either header missing or empty produces a 401
        response with error_id ERR_AUTH_HEADERS_MISSING.'

        Claim: empty X-User-ID value -> ERR_AUTH_HEADERS_MISSING / 401.
        """
        bad = {"X-User-ID": "", "X-User-Role": "PlatformAdmin"}
        res = api._request(
            "POST", "/distributors",
            create_distributor_payload(), bad,
        )
        validate_error(res, ApiErrorId.ERR_AUTH_HEADERS_MISSING.value)


# =========================================================================
# §2.1 -- RBAC: role-not-authorised yields ERR_ROLE_FORBIDDEN.
# =========================================================================
class TestRoleAuthorization:

    def test_distributor_cannot_create_distributor(
        self, api, distributor_ops_fallback_headers,
    ):
        """PRD §2.1: 'If both headers are present but the role is not
        authorized for the endpoint, the response is 403 with
        ERR_ROLE_FORBIDDEN.'
        PRD §4: POST /distributors is authorised only to PlatformAdmin.

        Claim: DistributorOps attempting POST /distributors -> 403.
        """
        res = api.create_distributor(
            create_distributor_payload(),
            distributor_ops_fallback_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_cinema_ops_cannot_create_film(
        self, api, cinema_ops_fallback_headers,
    ):
        """PRD §2.1: role authorization gate -> 403 ERR_ROLE_FORBIDDEN.
        PRD §4: POST /films is authorised only to DistributorOps.

        Claim: CinemaOps attempting POST /films -> 403.
        """
        res = api.create_film(
            create_film_payload(distributor_id="00000000-0000-0000-0000-000000000000"),
            cinema_ops_fallback_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN.value)

    def test_auditor_is_read_only(self, api, auditor_headers):
        """PRD §2.1: 'Auditor -- a strictly read-only role with access to
        every GET endpoint.'
        PRD §4: POST /distributors is authorised only to PlatformAdmin.

        Claim: Auditor attempting POST /distributors -> 403.
        """
        res = api.create_distributor(
            create_distributor_payload(), auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


# =========================================================================
# §2.2 -- Standard success envelope.
# =========================================================================
class TestResponseEnvelope:

    def test_success_envelope_keys(self, api, admin_headers):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with `meta`, `response_type`, and `data`.

        Claim: a 2xx response body has meta + response_type + data keys.
        """
        res = api.create_distributor(
            create_distributor_payload(), admin_headers,
        )
        body = res.json()
        for key in ("meta", "response_type", "data"):
            assert key in body, f"envelope missing key {key!r}"
        assert body["response_type"] in {"object", "array"}

    def test_error_envelope_keys(self, api):
        """PRD §2.2: error responses carry response_type 'error' with a
        data block containing error_id and message.

        Claim: a 4xx response body has meta + response_type='error' +
        data.error_id + data.message.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api._request("POST", "/distributors", {}, bad)
        body = res.json()
        assert body.get("response_type") == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]

    def test_create_returns_201(self, api, admin_headers):
        """PRD §4: 'Endpoint creation calls return HTTP 201 with the
        created resource in the envelope's data.'

        Claim: POST /distributors returns 201.
        """
        res = api.create_distributor(
            create_distributor_payload(), admin_headers,
        )
        validate_success(res, expected_status=201)


# =========================================================================
# §2.3 -- Pagination validation.
# =========================================================================
class TestPagination:

    @pytest.mark.parametrize("bad_params", [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ])
    def test_pagination_out_of_range(self, api, admin_headers, bad_params):
        """PRD §2.3: 'limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside that closed-closed range are
        rejected as ERR_BAD_REQUEST. offset defaults to 0 and must be at
        least 0.'

        Claim: out-of-range limit/offset -> ERR_BAD_REQUEST.
        """
        res = api.list_settlements(admin_headers, params=bad_params)
        validate_error(res, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_pagination_defaults(self, api, admin_headers):
        """PRD §2.3: 'limit defaults to 10 ... offset defaults to 0.'

        Claim: omitted pagination params -> meta.limit=10, meta.offset=0.
        """
        res = api.list_settlements(admin_headers)
        _data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_pagination_meta_keys(self, api, admin_headers):
        """PRD §2.3: 'The response meta block carries the request's
        limit and offset echoed back, along with total_count ... and
        has_more'.

        Claim: list response meta carries limit/offset/total_count/has_more.
        """
        res = api.list_settlements(admin_headers)
        _data, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta


# =========================================================================
# §2.5 -- Path existence checks fire before any deeper validation.
# =========================================================================
class TestPathExistence:

    def test_get_missing_distributor_returns_404(self, api, admin_headers):
        """PRD §2.5: 'URL path parameters are validated strictly from
        left to right. ... if the parent is missing the response is 404
        ERR_NOT_FOUND and no deeper checks run.'

        Claim: GET /distributors/{non-existent} -> 404 ERR_NOT_FOUND.
        """
        res = api.get_distributor(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_missing_film_returns_404(self, api, admin_headers):
        """PRD §2.5: path-existence yields 404 ERR_NOT_FOUND.

        Claim: GET /films/{non-existent} -> 404 ERR_NOT_FOUND.
        """
        res = api.get_film(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_missing_showtime_returns_404(self, api, admin_headers):
        """PRD §2.5: path-existence yields 404 ERR_NOT_FOUND.

        Claim: GET /showtimes/{non-existent} -> 404 ERR_NOT_FOUND.
        """
        res = api.get_showtime(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
