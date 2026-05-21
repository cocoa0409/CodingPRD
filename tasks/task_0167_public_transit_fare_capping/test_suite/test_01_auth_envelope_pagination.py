"""Authentication, role recognition, role permission, response envelope,
and pagination — PRD §2.1, §2.2, §2.3, §2.11.

These tests exercise the universal cross-cutting rules that apply to
every endpoint: missing headers, invalid role values, role-permission
mismatches, and pagination bounds.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to_iso,
    create_rider,
    create_rider_payload,
    setup_rider_with_funded_card,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth / role-recognition / role-permission probes
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_returns_err_auth_missing(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring their operational capacity. Requests missing either
        header are rejected with `ERR_AUTH_MISSING`."

        Claim: a request with neither header is rejected with
        ERR_AUTH_MISSING / 401."""
        resp = api._request("GET", "/transit/riders/" + NON_EXISTENT_UUID,
                            headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_returns_err_auth_missing(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        `ERR_AUTH_MISSING`.\""""
        resp = api._request("GET",
                            "/transit/riders/" + NON_EXISTENT_UUID,
                            headers={"X-User-Role": "AgencyOfficer"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_returns_err_auth_missing(self, api):
        """PRD §2.1: "Requests missing either header are rejected with
        `ERR_AUTH_MISSING`.\""""
        resp = api._request("GET",
                            "/transit/riders/" + NON_EXISTENT_UUID,
                            headers={"X-User-ID": "any-id"})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_unknown_role_returns_err_auth_invalid_role(self, api):
        """PRD §2.1: "The system recognises exactly four roles —
        `Rider`, `AgencyOfficer`, `EmployerAdmin`, and `Auditor` — and
        any other value in `X-User-Role` is rejected with
        `ERR_AUTH_INVALID_ROLE`.\""""
        resp = api._request(
            "GET", "/transit/riders/" + NON_EXISTENT_UUID,
            headers={"X-User-ID": "x", "X-User-Role": "SuperAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)

    def test_role_not_permitted_returns_forbidden(self, api,
                                                  auditor_headers):
        """PRD §2.1: "Once the role is recognised, the system checks
        that the role is permitted for the requested endpoint; a
        mismatch yields `ERR_FORBIDDEN`."

        Claim: Auditor is read-only and may not create riders (which is
        AgencyOfficer-only per §3.1 / §4)."""
        resp = api.create_rider(create_rider_payload(), auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_rider_cannot_create_rider(self, api, rider_headers):
        """PRD §4 endpoint table: POST /transit/riders is restricted to
        AgencyOfficer; PRD §2.1: "An `AgencyOfficer` creates riders and
        employers".

        Claim: Rider attempting POST /transit/riders → ERR_FORBIDDEN."""
        resp = api.create_rider(create_rider_payload(), rider_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_employer_admin_cannot_create_rider(self, api,
                                                employer_admin_headers):
        """PRD §4: POST /transit/riders → AgencyOfficer.
        Claim: EmployerAdmin attempting rider create → ERR_FORBIDDEN."""
        resp = api.create_rider(create_rider_payload(),
                                employer_admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope shape
# ===========================================================================
class TestResponseEnvelope:

    def test_success_response_envelope_shape(self, api,
                                             agency_officer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... `meta`
        ... `response_type` ... `data` ..."

        Claim: A 2xx response carries meta + response_type + data with
        api_request_id starting with `req_` and an ISO 8601 timestamp."""
        payload = create_rider_payload(email=unique_email())
        resp = api.create_rider(payload, agency_officer_headers)
        assert resp.status_code == 201, (
            f"Expected 201 for rider create, got {resp.status_code}"
        )
        body = resp.json()
        assert "meta" in body, "envelope missing 'meta'"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str), (
            "meta.api_request_id must be a string"
        )
        assert meta["api_request_id"].startswith("req_"), (
            "meta.api_request_id must start with 'req_'; "
            f"got {meta['api_request_id']!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)
        assert body.get("response_type") in {"object", "array"}, (
            f"response_type must be object/array, got "
            f"{body.get('response_type')!r}"
        )
        assert "data" in body, "envelope missing 'data'"

    def test_error_response_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... `response_type` is "error"
        ... `data` contains `error_id` and `message`."

        Claim: a 4xx response carries response_type=error and data.error_id."""
        resp = api._request(
            "GET", "/transit/riders/" + NON_EXISTENT_UUID, headers={},
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"response_type must be 'error', got "
            f"{body.get('response_type')!r}"
        )
        data = body.get("data", {})
        assert isinstance(data.get("error_id"), str), (
            "error data must carry error_id string"
        )
        assert isinstance(data.get("message"), str), (
            "error data must carry message string"
        )


# ===========================================================================
# Pagination bounds — PRD §2.3
# ===========================================================================
class TestPaginationBounds:

    def test_default_pagination_returns_meta(self, api,
                                             agency_officer_headers):
        """PRD §2.3: "List responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Claim: GET /transit/trips returns meta with the four pagination
        fields."""
        resp = api.list_trips(agency_officer_headers)
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing pagination key {key!r}"

    def test_limit_zero_rejected(self, api, agency_officer_headers):
        """PRD §2.3: "A `limit` outside the range or a negative
        `offset` is rejected with `ERR_INVALID_PAGINATION`."

        Claim: limit=0 is below the minimum (1) → ERR_INVALID_PAGINATION."""
        resp = api.list_trips(agency_officer_headers, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_above_max_rejected(self, api, agency_officer_headers):
        """PRD §2.3: "if not provided, it defaults to 10, with a
        minimum of 1 and a maximum of 100"; "A `limit` outside the
        range ... is rejected with `ERR_INVALID_PAGINATION`."

        Claim: limit=101 exceeds the max → ERR_INVALID_PAGINATION."""
        resp = api.list_trips(agency_officer_headers, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_negative_offset_rejected(self, api, agency_officer_headers):
        """PRD §2.3: "The `offset` parameter ... must be zero or
        greater"; "A `limit` outside the range or a negative `offset`
        is rejected with `ERR_INVALID_PAGINATION`."

        Claim: offset=-1 → ERR_INVALID_PAGINATION."""
        resp = api.list_trips(agency_officer_headers,
                              params={"offset": -1})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_at_minimum_is_accepted(self, api,
                                          agency_officer_headers):
        """PRD §2.3: "with a minimum of 1 and a maximum of 100".

        Claim: limit=1 is at the inclusive minimum and is accepted."""
        resp = api.list_trips(agency_officer_headers, params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    def test_limit_at_maximum_is_accepted(self, api,
                                          agency_officer_headers):
        """PRD §2.3: "with a minimum of 1 and a maximum of 100".

        Claim: limit=100 is at the inclusive maximum and is accepted."""
        resp = api.list_trips(agency_officer_headers, params={"limit": 100})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 100
