"""Authentication, response envelope, and pagination.

PRD §2.1 (RBAC headers), §2.2 (envelope), §2.3 (pagination), §2.4
(resource identity / timestamps / versioning).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_station_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_station_with_staff,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# PRD §2.1 -- header presence and role authorization
# ===========================================================================
class TestAuthHeaders:
    def test_missing_role_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_MISSING and HTTP 401."

        Claim: omitting X-User-Role yields ERR_AUTH_MISSING at HTTP 401.
        """
        resp = api._request("GET", "/stations", None,
                            {"X-User-ID": "anyone"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_missing_user_id_header_returns_err_auth_missing(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_MISSING and HTTP 401."

        Claim: omitting X-User-ID yields ERR_AUTH_MISSING at HTTP 401.
        """
        resp = api._request("GET", "/stations", None,
                            {"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING)

    def test_role_not_authorized_returns_forbidden(self, api,
                                                   recipient_headers):
        """PRD §2.1: "A request whose role is not authorized for the
        requested operation is rejected with ERR_FORBIDDEN and HTTP 403."

        Claim: a Recipient cannot POST /stations (PlatformAdmin only).
        """
        resp = api.create_station(create_station_payload(), recipient_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# PRD §2.2 -- success and error envelopes
# ===========================================================================
class TestEnvelopeStructure:
    def test_success_envelope_has_meta_and_data(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format" with a
        `meta` object carrying `api_request_id` and
        `api_request_timestamp` and a `data` payload.

        Claim: POST /stations returns an envelope with meta.api_request_id
        and data is the Station object.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        # validate_success unwraps the data payload; the envelope shape
        # checks (api_request_id starts with 'req_', response_type, etc.)
        # are enforced by validate_success itself.
        assert is_valid_uuid(data["id"])

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: an error response body carries data.error_id and
        data.message.
        """
        resp = api._request("GET", "/stations", None, {})  # no headers
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_AUTH_MISSING"
        assert isinstance(body["data"].get("message"), str)


# ===========================================================================
# PRD §2.3 -- pagination
# ===========================================================================
class TestPagination:
    def test_list_returns_pagination_meta(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "The meta block of a list response includes limit,
        offset, total_count, and has_more derived from the underlying
        scan."

        Claim: GET /stations returns a meta dict with these four keys.
        """
        resp = api.list_stations(platform_admin_headers)
        data, meta = validate_paginated(resp)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing {k}"
        assert isinstance(data, list)

    def test_list_default_limit_is_10(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: "All list endpoints accept two query parameters: limit and offset. The default limit is 10, the minimum is 1, the maximum is 100; values outside this range yield ERR_VALIDATION."

        Claim: omitting `limit` yields meta.limit == 10.
        """
        resp = api.list_stations(platform_admin_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 200])
    def test_list_limit_out_of_range_yields_validation(
        self, api, platform_admin_headers, bad_limit,
    ):
        """PRD §2.3: "the minimum is 1, the maximum is 100; values
        outside this range yield ERR_VALIDATION."

        Claim: limit outside [1, 100] yields ERR_VALIDATION.
        """
        resp = api.list_stations(
            platform_admin_headers, params={"limit": bad_limit},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ===========================================================================
# PRD §2.4 -- ids, timestamps, version
# ===========================================================================
class TestResourceIdentity:
    def test_created_station_has_uuid_iso_timestamps_version_zero(
        self, api, platform_admin_headers,
    ):
        """PRD §2.4: "Every resource carries a server-minted id that is
        a UUID string with no type prefix. Resources whose specification
        declares the common-fields set additionally carry created_at and
        updated_at (ISO 8601 UTC timestamps with three fractional
        digits), and version (a non-negative integer that increments by
        one on every successful mutation)."

        Claim: POST /stations response carries UUID id, ISO 8601
        created_at and updated_at, and a non-negative integer version.
        """
        resp = api.create_station(
            create_station_payload(), platform_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int) and data["version"] >= 0

    def test_resource_not_found_for_unknown_station_id(
        self, api, platform_admin_headers,
    ):
        """PRD §2.5: "Any unresolved segment, in order, yields
        ERR_RESOURCE_NOT_FOUND with HTTP 404."

        Claim: GET /stations/{nonexistent} yields ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_station(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


# ===========================================================================
# PRD §2.6 -- optimistic concurrency
# ===========================================================================
class TestOptimisticConcurrency:
    def test_patch_with_stale_version_yields_version_conflict(self, api):
        """PRD §2.6: "When the client supplies version, the server
        compares it against the current entity's version; a mismatch
        yields ERR_VERSION_CONFLICT with HTTP 409, and the request is
        otherwise refused without side effect."

        Claim: PATCH /stations/{id} with a stale version returns
        ERR_VERSION_CONFLICT.
        """
        ctx = setup_station_with_staff()
        station = ctx["station"]
        resp = api.patch_station(
            station["id"],
            {"name": "Renamed", "version": station["version"] + 99},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)

    def test_patch_without_version_skips_occ(self, api):
        """PRD §2.6: "When the client omits version, the OCC check is
        skipped and the mutation proceeds against the latest row."

        Claim: PATCH /stations/{id} without a version field succeeds.
        """
        ctx = setup_station_with_staff()
        station = ctx["station"]
        resp = api.patch_station(
            station["id"], {"name": "RenamedNoOcc"},
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(resp)
        assert data["name"] == "RenamedNoOcc"
        assert data["version"] == station["version"] + 1
