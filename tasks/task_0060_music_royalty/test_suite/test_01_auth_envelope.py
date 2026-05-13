"""Tests for global auth and response-envelope contracts (PRD §2.1, §2.2,
§2.10 priorities 1–3)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_rights_holder_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMissingHeaders:
    """PRD §2.1 / §2.10 priority 1: both X-User-Role and X-User-ID must be
    present; missing yields ERR_AUTH_REQUIRED with HTTP 401."""

    def test_missing_role_returns_auth_required(self, api):
        """PRD §2.1: 'Every request to the API must include two headers:
        X-User-Role and X-User-ID. Either header missing yields
        ERR_AUTH_REQUIRED with HTTP 401.'

        Claim: omitting X-User-Role on any endpoint → ERR_AUTH_REQUIRED (401).
        """
        resp = api._request(
            "GET", "/royalty/rights-holders",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value, 401)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: 'Every request to the API must include two headers:
        X-User-Role and X-User-ID. Either header missing yields
        ERR_AUTH_REQUIRED with HTTP 401.'

        Claim: omitting X-User-ID on any endpoint → ERR_AUTH_REQUIRED (401).
        """
        resp = api._request(
            "GET", "/royalty/rights-holders",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value, 401)

    def test_both_headers_missing_returns_auth_required(self, api):
        """PRD §2.1: 'Every request to the API must include two headers:
        X-User-Role and X-User-ID.'

        Claim: omitting BOTH auth headers → ERR_AUTH_REQUIRED (401).
        """
        resp = api._request("GET", "/royalty/rights-holders", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value, 401)


class TestUnknownRole:
    """PRD §2.1 / §2.10 priority 2: an X-User-Role value that is not one
    of the six declared roles also yields ERR_AUTH_REQUIRED."""

    def test_unknown_role_returns_auth_required(self, api):
        """PRD §2.1: 'Either header missing yields ERR_AUTH_REQUIRED with
        HTTP 401, as does an X-User-Role value that is not one of the six
        declared roles.'

        Claim: unknown role string → ERR_AUTH_REQUIRED (401).
        """
        headers = build_user_headers("anyone-001", "InvaderRole")
        resp = api.list_rights_holders(headers)
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value, 401)


class TestForbiddenRole:
    """PRD §2.1 / §2.10 priority 3: authenticated but not permitted →
    ERR_FORBIDDEN (HTTP 403)."""

    @pytest.mark.parametrize("role,user_id", [
        ("RightsHolder", "holder-x"),
        ("FinanceOps", "fin-x"),
        ("RegistrationReviewer", "rev-x"),
        ("DisputeOfficer", "doff-x"),
    ])
    def test_non_admin_cannot_create_rights_holder(self, api, role, user_id):
        """PRD §2.1: 'When an authenticated caller invokes an endpoint
        they are not permitted to use, the request is rejected with
        ERR_FORBIDDEN and HTTP 403.' PRD §4: POST /royalty/rights-holders
        is restricted to PlatformAdmin.

        Claim: non-PlatformAdmin POST /royalty/rights-holders →
        ERR_FORBIDDEN (403).
        """
        headers = build_user_headers(user_id, role)
        resp = api.create_rights_holder(create_rights_holder_payload(),
                                        headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)

    def test_finance_cannot_open_dispute(self, api, finance_headers):
        """PRD §4: POST /royalty/disputes is restricted to RightsHolder.

        Claim: FinanceOps cannot open a dispute → ERR_FORBIDDEN (403).
        """
        resp = api.create_dispute(
            {"work_id": NON_EXISTENT_UUID, "dispute_kind": "OWNERSHIP",
             "claim_summary": "test"},
            finance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


class TestNotFound:
    """PRD §2.10 priority 4 / §2.5: every path-referenced resource must
    exist; a missing resource yields ERR_NOT_FOUND (HTTP 404)."""

    def test_get_unknown_rights_holder_returns_not_found(self, api, pa_headers):
        """PRD §2.5: 'Any failure along this chain returns ERR_NOT_FOUND
        (HTTP 404) keyed to the first segment that fails.'

        Claim: GET /royalty/rights-holders/{unknown} → ERR_NOT_FOUND (404).
        """
        resp = api.get_rights_holder(NON_EXISTENT_UUID, pa_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_get_unknown_work_returns_not_found(self, api, pa_headers):
        """PRD §2.5: 'Any failure along this chain returns ERR_NOT_FOUND
        (HTTP 404).'

        Claim: GET /royalty/works/{unknown} → ERR_NOT_FOUND (404).
        """
        resp = api.get_work(NON_EXISTENT_UUID, pa_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestSuccessEnvelope:
    """PRD §2.2: every 2xx body carries meta + response_type + data."""

    def test_list_rights_holders_envelope(self, api, pa_headers):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body.'

        Claim: list endpoint returns envelope with meta.api_request_id,
        meta.api_request_timestamp, pagination meta, response_type, data.
        """
        resp = api.list_rights_holders(pa_headers, params={"limit": 5})
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "limit" in meta and meta["limit"] == 5
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta

    def test_object_response_carries_iso_timestamp_and_request_id(self, api,
                                                                  pa_headers):
        """PRD §2.2: 'api_request_id is a server-generated unique
        identifier for the request that starts with req_' and
        'api_request_timestamp is a server-generated ISO 8601 UTC
        timestamp with three fractional digits.'

        Claim: response.meta.api_request_id starts with 'req_' and
        api_request_timestamp is an ISO 8601 timestamp.
        """
        resp = api.create_rights_holder(create_rights_holder_payload(),
                                        pa_headers)
        body = resp.json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] in {"object", "array"}


class TestPagination:
    """PRD §2.3."""

    def test_limit_defaults_to_ten(self, api, pa_headers):
        """PRD §2.3: 'The limit parameter defaults to 10 when omitted.'

        Claim: omitting limit on a list endpoint yields meta.limit == 10.
        """
        resp = api.list_rights_holders(pa_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_offset_defaults_to_zero(self, api, pa_headers):
        """PRD §2.3: 'The offset parameter defaults to 0.'

        Claim: omitting offset on a list endpoint yields meta.offset == 0.
        """
        resp = api.list_rights_holders(pa_headers, params={"limit": 3})
        _, meta = validate_paginated(resp)
        assert meta["offset"] == 0
        assert meta["limit"] == 3
