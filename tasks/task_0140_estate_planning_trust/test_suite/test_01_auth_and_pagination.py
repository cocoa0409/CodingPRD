"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.4):
- Missing X-User-Role / X-User-ID header -> ERR_AUTH_REQUIRED (401).
- Role not permitted for endpoint -> ERR_FORBIDDEN (403).
- Pagination parameter bounds.
- Response envelope shape.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    api_client,
    create_estate,
    create_estate_with_executor,
    create_hipaa_payload,
    setup_in_probate,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing-header tests — PRD §2.1
# ===========================================================================
class TestAuthMissingHeaders:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Every request to the API must carry two headers:
        X-User-ID, identifying the acting user, and X-User-Role,
        declaring the role under which the user is acting. Either
        header missing or empty causes the request to be rejected
        with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: omitting both auth headers -> ERR_AUTH_REQUIRED / 401.
        """
        resp = api._request("GET", "/estates/anything", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Either header missing or empty causes the
        request to be rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/estates/anything",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Either header missing or empty causes the
        request to be rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/estates/anything",
            headers={"X-User-Role": "Executor"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_role_value_rejected(self, api):
        """PRD §2.1: "Either header missing or empty causes the
        request to be rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: empty-string X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/estates/anything",
            headers={"X-User-Role": "", "X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_value_rejected(self, api):
        """PRD §2.1: "Either header missing or empty causes the
        request to be rejected with ERR_AUTH_REQUIRED and HTTP 401."

        Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/estates/anything",
            headers={"X-User-Role": "Executor", "X-User-ID": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role-forbidden tests — PRD §2.1
# ===========================================================================
class TestAuthForbidden:

    def test_beneficiary_cannot_advance_clock(self, api,
                                              beneficiary_fallback_headers):
        """PRD §2.1: "A request that supplies headers but whose role
        is not authorized for the endpoint receives ERR_FORBIDDEN and
        HTTP 403."

        Claim: Beneficiary attempting CourtClerk-only POST
        /_clock/advance -> ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            payload={"to_timestamp": "2030-01-01T00:00:00.000Z"},
            headers=beneficiary_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_court_clerk_cannot_create_estate(self, api,
                                              court_clerk_headers):
        """PRD §2.1: "A request that supplies headers but whose role
        is not authorized for the endpoint receives ERR_FORBIDDEN and
        HTTP 403."

        Claim: CourtClerk attempting Executor-only POST /estates ->
        ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/estates",
            payload={
                "testator_name": "x",
                "domicile_state": "NY",
                "filing_court_id": "ct-1",
            },
            headers=court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with meta.api_request_id, api_request_timestamp,
        response_type, data.

        Claim: a 201 estate-create response carries the envelope.
        """
        estate = create_estate()
        # estate is the data field; the envelope validation already
        # happened via get_success_data in create_estate. Spot-check
        # by re-reading the estate via the raw API.
        resp = api_client.get_estate(
            estate["id"], TEST_USERS["court_clerk_headers"],
        )
        body = resp.json()
        assert "meta" in body, "envelope must carry 'meta'"
        assert "response_type" in body, (
            "envelope must carry 'response_type'"
        )
        assert "data" in body, "envelope must carry 'data'"
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and (
            meta["api_request_id"].startswith("req_")
        ), (
            "meta.api_request_id must be string starting with req_; "
            f"got {meta.get('api_request_id')!r}"
        )

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with response_type
        'error' and data.error_id + data.message.

        Claim: a 401 carries response_type='error' and error_id +
        message strings.
        """
        resp = api._request("GET", "/estates/anything", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body.get("data", {}).get("error_id"), str)
        assert isinstance(body.get("data", {}).get("message"), str)
        assert body["data"]["message"].strip()


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_10(self, api, court_clerk_headers):
        """PRD §2.3: "The default limit is 10".

        Claim: a list response with no limit param uses limit=10 in
        meta.
        """
        resp = api_client.list_estates(court_clerk_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"default limit must be 10, got {meta['limit']}"
        )

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 1000])
    def test_limit_out_of_range_rejected(self, api,
                                         court_clerk_headers,
                                         bad_limit):
        """PRD §2.3: "the minimum is 1, and the maximum is 100; a
        request asking for a limit outside that band is rejected
        with ERR_BAD_REQUEST."

        Claim: limit < 1 or > 100 -> ERR_BAD_REQUEST.
        """
        resp = api_client.list_estates(
            court_clerk_headers, params={"limit": bad_limit},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_negative_offset_rejected(self, api, court_clerk_headers):
        """PRD §2.3: "The default offset is 0 and offset may not be
        negative."

        Claim: offset < 0 -> ERR_BAD_REQUEST.
        """
        resp = api_client.list_estates(
            court_clerk_headers, params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_max_limit_accepted(self, api, court_clerk_headers):
        """PRD §2.3: "the maximum is 100".

        Claim: limit=100 (boundary) is accepted.
        """
        resp = api_client.list_estates(
            court_clerk_headers,
            params={"limit": PAGINATION_MAX_LIMIT},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_MAX_LIMIT


# ===========================================================================
# Nested path / NotFound — PRD §2.5
# ===========================================================================
class TestNestedNotFound:

    def test_get_estate_not_found(self, api, court_clerk_headers):
        """PRD §2.5: "Any miss along the way yields ERR_NOT_FOUND
        with HTTP 404, including the case where the nested id refers
        to a resource that exists but is parented to a different
        estate."

        Claim: GET /estates/<nonexistent> -> ERR_NOT_FOUND.
        """
        resp = api_client.get_estate(
            "00000000-0000-0000-0000-000000000000",
            court_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_asset_with_wrong_parent_estate(self, api):
        """PRD §2.5: "Any miss along the way yields ERR_NOT_FOUND
        ..., including the case where the nested id refers to a
        resource that exists but is parented to a different estate."

        Claim: GET /estates/{otherEstateId}/assets/{realAssetId} ->
        ERR_NOT_FOUND.
        """
        # Create two estates; create an asset under the first;
        # request it under the second.
        e1, _, exec_h_1 = create_estate_with_executor()
        e2, _, _ = create_estate_with_executor()
        # Declare an asset on e1.
        from test_helpers import declare_asset
        a = declare_asset(
            e1["id"], asset_class="FINANCIAL",
            declared_value_cents=1000, exec_headers=exec_h_1,
        )
        resp = api_client.get_asset(
            e2["id"], a["id"],
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
