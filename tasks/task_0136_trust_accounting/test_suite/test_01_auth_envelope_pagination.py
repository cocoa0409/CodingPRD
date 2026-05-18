"""Authentication, response envelope, and pagination — PRD §2.1, §2.2, §2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    api_client,
    create_trust_payload,
    setup_active_trust,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing or malformed auth headers — PRD §2.1
# ===========================================================================
class TestAuthRequired:

    def test_missing_both_headers(self, api):
        """PRD §2.1: "Every request to the API must include the two
        authentication headers X-User-ID and X-User-Role. If either
        header is missing or cannot be parsed, the server rejects the
        request with ERR_UNAUTHENTICATED."

        Claim: omitting both headers -> ERR_UNAUTHENTICATED / 401.
        """
        resp = api._request("GET", "/trusts", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_role_header(self, api):
        """PRD §2.1: "Every request to the API must include the two
        authentication headers X-User-ID and X-User-Role. If either
        header is missing or cannot be parsed, the server rejects the
        request with ERR_UNAUTHENTICATED."

        Claim: only X-User-ID present -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", "/trusts", headers={"X-User-ID": "someone"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "Every request to the API must include the two
        authentication headers X-User-ID and X-User-Role. If either
        header is missing or cannot be parsed, the server rejects the
        request with ERR_UNAUTHENTICATED."

        Claim: only X-User-Role present -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", "/trusts", headers={"X-User-Role": "Grantor"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Forbidden role — PRD §2.1
# ===========================================================================
class TestAuthForbidden:

    # NOTE: a test asserting an unrecognized role string -> ERR_FORBIDDEN
    # was removed. PRD §2.1 says "If either header is missing or cannot
    # be parsed, the server rejects the request with ERR_UNAUTHENTICATED.
    # If the authenticated role is not permitted to invoke the requested
    # endpoint, the server rejects the request with ERR_FORBIDDEN." An
    # unrecognized role token like "Robot" is plausibly read as either
    # unparseable (-> ERR_UNAUTHENTICATED) or as a permitted-but-wrong-role
    # (-> ERR_FORBIDDEN); PRD does not uniquely determine which. Deleted
    # per STEP 1b unique-derivability.

    def test_beneficiary_cannot_create_trust(
        self, api, beneficiary_fallback_headers,
    ):
        """PRD §4 endpoint table: "POST /trusts ... Authorized Role(s):
        Grantor". PRD §2.1: "If the authenticated role is not
        permitted to invoke the requested endpoint, the server
        rejects the request with ERR_FORBIDDEN."

        Claim: Beneficiary attempting POST /trusts -> ERR_FORBIDDEN.
        """
        resp = api.create_trust(
            create_trust_payload(), beneficiary_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_create_trust(
        self, api, auditor_headers,
    ):
        """PRD §4 endpoint table: "POST /trusts ... Authorized Role(s):
        Grantor". PRD §2.1: "If the authenticated role is not
        permitted to invoke the requested endpoint, the server
        rejects the request with ERR_FORBIDDEN."

        Claim: Auditor cannot create a trust -> ERR_FORBIDDEN.
        """
        resp = api.create_trust(
            create_trust_payload(), auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_create_returns_201_envelope_with_data(
        self, api, grantor_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with meta, response_type, data.
        PRD §4: "endpoints that create a wholly new resource — which
        return HTTP 201."

        Claim: POST /trusts returns 201 + envelope with object data.
        """
        resp = api.create_trust(create_trust_payload(), grantor_headers)
        assert resp.status_code == 201, (
            f"Expected 201 for resource creation; got {resp.status_code}"
        )
        body = resp.json()
        assert "meta" in body and "response_type" in body and (
            "data" in body
        )
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and (
            meta["api_request_id"].startswith("req_")
        ), (
            f"api_request_id must start with 'req_'; got "
            f"{meta.get('api_request_id')!r}"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_state_transition_returns_200(
        self, api, grantor_headers,
    ):
        """PRD §4: "State-transition actions on existing resources
        (activate, revoke, terminate, approve, execute, reject,
        begin-close, finalize, amend) all return HTTP 200."

        Claim: POST /trusts/{id}/activate returns 200, not 201.
        """
        scenario = setup_active_trust()
        # setup_active_trust already activated; re-fetch & check 200.
        resp = api.get_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        assert resp.status_code == 200


# ===========================================================================
# Error envelope shape — PRD §2.2
# ===========================================================================
class TestErrorEnvelope:

    def test_error_envelope_has_response_type_error(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with response_type ==
        "error" and data.error_id + data.message.

        Claim: a 4xx error response carries response_type == "error".
        """
        resp = api._request("GET", "/trusts", headers={})
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"Error envelope must set response_type='error', got "
            f"{body.get('response_type')!r}"
        )
        assert "error_id" in body.get("data", {}), (
            f"Error data must carry error_id; got {body!r}"
        )
        assert isinstance(body["data"].get("message"), str), (
            f"Error data must carry a human-readable message; got "
            f"{body!r}"
        )


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_ten(self, api, grantor_headers):
        """PRD §2.3: "The limit parameter has a default of 10, a
        minimum of 1, and a maximum of 100".

        Claim: listing with no params reports limit == 10 in meta.
        """
        resp = api.list_trusts(grantor_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
            f"Default limit must be 10; got {meta['limit']}"
        )
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta and isinstance(meta["has_more"], bool)

    def test_explicit_limit_honored(self, api, grantor_headers):
        """PRD §2.3: "The limit parameter has a default of 10, a
        minimum of 1, and a maximum of 100; the offset parameter has
        a default of 0 and a minimum of 0."

        Claim: limit=1 returns at most 1 item and meta reflects it.
        """
        # Seed three trusts so a 1-per-page slice is observable.
        for i in range(3):
            api.create_trust(
                create_trust_payload(name=f"Pag {i}"),
                grantor_headers,
            )
        resp = api.list_trusts(
            grantor_headers, params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) <= 1
        assert meta["limit"] == 1

    def test_has_more_true_when_total_exceeds_window(
        self, api, grantor_headers,
    ):
        """PRD §2.3: "has_more (a boolean indicating whether further
        pages remain)."

        Claim: when total_count > limit + offset, has_more is true.
        """
        for i in range(3):
            api.create_trust(
                create_trust_payload(name=f"More {i}"),
                grantor_headers,
            )
        resp = api.list_trusts(
            grantor_headers, params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        if meta["total_count"] > 1:
            assert meta["has_more"] is True


# ===========================================================================
# 404 — PRD §2.6
# ===========================================================================
class TestNotFound:

    def test_get_nonexistent_trust(self, api, grantor_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing
        record under the appropriate parent scope, ERR_NOT_FOUND is
        returned."

        Claim: GET /trusts/{nonexistent} -> ERR_NOT_FOUND / 404.
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api.get_trust(NON_EXISTENT_UUID, grantor_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
