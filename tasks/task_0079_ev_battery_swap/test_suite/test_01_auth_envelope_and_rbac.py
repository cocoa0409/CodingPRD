"""Auth headers, response envelope, RBAC, and pagination.

Covers PRD §2.1 (auth headers), §2.2 (envelope), §2.3 (pagination), §5
(generic error catalogue).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_station_payload,
    make_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing the server rejects the
        request with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-ID on any endpoint → ERR_AUTH_REQUIRED 401.
        """
        # Build headers with only X-User-Role; X-User-ID missing.
        resp = api._request(
            "GET", "/swap-stations/stations",
            headers={
                "X-User-Role": "PlatformAdmin",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing the server rejects the
        request with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-Role → ERR_AUTH_REQUIRED 401.
        """
        resp = api._request(
            "GET", "/swap-stations/stations",
            headers={
                "X-User-ID": "anyone",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "If X-User-Role is not one of the three recognised
        values — Member, StationOperator, PlatformAdmin — the request is
        rejected with ERR_FORBIDDEN and HTTP 403."

        Claim: unknown X-User-Role string → ERR_FORBIDDEN 403.
        """
        resp = api._request(
            "GET", "/swap-stations/stations",
            headers={
                "X-User-ID": "anyone",
                "X-User-Role": "Nobody",
                "Content-Type": "application/json",
            },
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestRbacExclusivity:
    @pytest.mark.parametrize("role,expected_error", [
        ("Member", ApiErrorId.ERR_FORBIDDEN.value),
        ("StationOperator", ApiErrorId.ERR_FORBIDDEN.value),
    ])
    def test_only_platform_admin_can_register_station(self, api,
                                                     role, expected_error):
        """PRD §2.1: "the same error is returned when an authenticated
        caller addresses an endpoint not authorised for their role."

        Claim: non-admin role attempting POST /stations → ERR_FORBIDDEN.
        (POST /stations is PlatformAdmin-exclusive per PRD §4 endpoint table.)
        """
        headers = {
            "X-User-ID": "irrelevant",
            "X-User-Role": role,
            "Content-Type": "application/json",
        }
        resp = api.create_station(create_station_payload(), headers)
        validate_error(resp, expected_error)


class TestResponseEnvelope:
    def test_success_envelope_has_meta_and_data(self, api, platform_admin_headers):
        """PRD §2.2: success body has meta with api_request_id starting
        with req_, an ISO 8601 api_request_timestamp, a response_type,
        and a data field.

        Claim: a 200/201 response carries the documented envelope keys.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id 'starts with req_'"
        )

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: error envelope data has 'error_id' (machine-readable)
        and 'message' (human-readable).

        Claim: missing-auth produces the standard error envelope shape.
        """
        resp = api._request("GET", "/swap-stations/stations", headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


class TestPagination:
    def test_default_limit_is_ten(self, api, platform_admin_headers):
        """PRD §2.3: "The default limit is 10".

        Claim: list endpoint without explicit limit returns meta.limit == 10.
        """
        resp = api.list_stations(platform_admin_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            "PRD §2.3 default limit is 10"
        )

    @pytest.mark.parametrize("limit", [0, 101, -1])
    def test_limit_out_of_bounds_rejected(self, api,
                                          platform_admin_headers, limit):
        """PRD §2.3: "the minimum is 1, and the maximum is 100 ... A value
        outside these ranges is rejected with ERR_INVALID_PAGINATION and
        HTTP 422."

        Claim: limit=0/101/-1 → ERR_INVALID_PAGINATION 422.
        """
        resp = api.list_stations(
            platform_admin_headers, params={"limit": limit},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_negative_offset_rejected(self, api, platform_admin_headers):
        """PRD §2.3: "the default offset is 0 and it must be at least 0."

        Claim: offset=-1 → ERR_INVALID_PAGINATION 422.
        """
        resp = api.list_stations(
            platform_admin_headers, params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)


class TestNotFound:
    def test_get_station_unknown_id_404(self, api, platform_admin_headers):
        """PRD §2.6: "if it does not exist the response is ERR_NOT_FOUND
        with HTTP 404".

        Claim: GET on an unknown station id → ERR_NOT_FOUND 404.
        """
        resp = api.get_station(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
