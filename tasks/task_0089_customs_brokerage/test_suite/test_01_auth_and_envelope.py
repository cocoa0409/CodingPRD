"""Auth, response envelope, and RBAC tests (PRD §2.1, §2.2, §2.10)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_agreement_payload,
    create_client_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §2.1 — Missing / empty auth headers → ERR_AUTH_MISSING
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "Every request to the API must carry two headers:
        X-User-ID, identifying the calling principal, and X-User-Role,
        naming one of the eight roles defined for this system. If
        either header is missing or empty, the server returns
        ERR_AUTH_MISSING with HTTP 401."

        Claim: omitting X-User-ID → ERR_AUTH_MISSING (401).
        """
        resp = api._request(
            "GET", "/customs/clients",
            headers={"X-User-Role": "BrokerOps"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the server
        returns ERR_AUTH_MISSING with HTTP 401."

        Claim: omitting X-User-Role → ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/customs/clients",
            headers={"X-User-ID": "broker-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the server
        returns ERR_AUTH_MISSING with HTTP 401."

        Claim: empty-string X-User-ID is treated as missing.
        """
        resp = api._request(
            "GET", "/customs/clients",
            headers={"X-User-ID": "", "X-User-Role": "BrokerOps"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_role_header_returns_auth_missing(self, api):
        """PRD §2.1: "If either header is missing or empty, the server
        returns ERR_AUTH_MISSING with HTTP 401."

        Claim: empty-string X-User-Role is treated as missing.
        """
        resp = api._request(
            "GET", "/customs/clients",
            headers={"X-User-ID": "broker-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# §2.1 / §2.10 — Forbidden role → ERR_FORBIDDEN, evaluated after auth
# ===========================================================================
class TestRoleForbidden:

    def test_declaration_officer_cannot_create_client(self, api,
                                                      declaration_officer_headers):
        """PRD §2.1: "If the headers are present but the role named by
        X-User-Role is not permitted to invoke the endpoint, the server
        returns ERR_FORBIDDEN with HTTP 403."
        PRD §4: POST /customs/clients is restricted to BrokerOps, SystemAdmin.

        Claim: DeclarationOfficer creating a client → ERR_FORBIDDEN.
        """
        resp = api.create_client(create_client_payload(),
                                 declaration_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_client_user_cannot_create_agreement(self, api,
                                                 client_user_fallback_headers):
        """PRD §2.1: "If the headers are present but the role named by
        X-User-Role is not permitted to invoke the endpoint, the server
        returns ERR_FORBIDDEN with HTTP 403."
        PRD §4: POST /customs/agreements is restricted to BrokerOps.

        Claim: ClientUser creating an agreement → ERR_FORBIDDEN.
        """
        resp = api.create_agreement(
            create_agreement_payload(client_id="00000000-0000-0000-0000-000000000000"),
            client_user_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_filing_officer_cannot_pre_validate(self, api, filing_officer_headers,
                                                broker_ops_headers):
        """PRD §4: POST /customs/declarations/{id}/pre-validate is
        restricted to DocReviewer.

        Claim: a FilingOfficer cannot invoke /pre-validate → ERR_FORBIDDEN.
        """
        # PRD §2.10: existence (priority 20) outranks authorization (10),
        # but PRD §2.10 places auth checks ahead of existence. The path
        # below uses a syntactically valid but non-existent id; we
        # rely on the role check firing before existence per PRD §2.10:
        # "Authentication checks for X-User-Role and X-User-ID fire first,
        # followed by role authorization, followed by left-to-right path
        # existence...".
        resp = api.pre_validate_declaration(
            "00000000-0000-0000-0000-000000000000", {}, filing_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §2.2 — Response envelope
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_carries_meta_and_data(self, api, broker_ops_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body:
        { 'meta': { 'api_request_id': ..., 'api_request_timestamp': ... },
          'response_type': 'object' | 'array', 'data': { } }".

        Claim: success envelope carries meta.api_request_id, meta.api_request_timestamp,
        response_type, and data.
        """
        payload = create_client_payload()
        resp = api.create_client(payload, broker_ops_headers)
        body = resp.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_ (PRD §2.2)"
        )
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] in ("object", "array")
        assert "data" in body

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format: data: { 'error_id': '...',
        'message': 'A human-readable explanation of the error.' }".

        Claim: error responses carry error_id and message in data.
        """
        resp = api._request("GET", "/customs/clients", headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# §2.3 — Pagination defaults and meta fields
# ===========================================================================
class TestPagination:

    def test_list_clients_returns_pagination_meta(self, api, broker_ops_headers):
        """PRD §2.3: "The response envelope's meta object exposes four
        pagination fields for list endpoints: the limit and offset that
        were applied, the total_count of records matching the filter
        (across the entire collection, not the current page), and a
        boolean has_more indicating whether further records exist
        beyond the current page."

        Claim: list endpoint meta carries limit/offset/total_count/has_more.
        """
        resp = api.list_clients(broker_ops_headers)
        body = resp.json()
        meta = body["meta"]
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(meta["has_more"], bool)

    def test_list_clients_default_limit_is_ten(self, api, broker_ops_headers):
        """PRD §2.3: "The default value of limit is 10; its minimum is 1
        and its maximum is 100."

        Claim: omitted limit query param defaults to 10.
        """
        resp = api.list_clients(broker_ops_headers)
        body = resp.json()
        assert body["meta"]["limit"] == 10
