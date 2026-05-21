"""Auth headers, role-based access control, response envelope, pagination.

PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.7 (path
validation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_election_payload,
    setup_election_with_precinct,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or whose
        headers cannot be parsed, is rejected with ERR_UNAUTHENTICATED."

        Claim: GET /elections with no headers → ERR_UNAUTHENTICATED.
        """
        resp = api._request("GET", "/elections", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or whose
        headers cannot be parsed, is rejected with ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/elections",
            headers={"X-User-Role": "ElectionBoard"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or whose
        headers cannot be parsed, is rejected with ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/elections",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize("role", [
        "ElectionBoard", "RegistrarClerk", "ReviewerClerk",
        "PrecinctOfficer", "Voter", "TestDriver",
    ])
    def test_each_of_six_roles_clears_auth(self, api, role):
        """PRD §2.1: "The system recognises six roles: ElectionBoard,
        RegistrarClerk, ReviewerClerk, PrecinctOfficer, Voter, and
        TestDriver."

        Claim: each named role is accepted at the authentication gate.
        """
        headers = build_user_headers(f"user-{role.lower()}", role)
        resp = api._request("GET", "/elections", headers=headers)
        if resp.status_code == 401:
            body = resp.json().get("data", {}) or {}
            assert body.get("error_id") != (
                ApiErrorId.ERR_UNAUTHENTICATED.value
            ), f"role {role!r} should clear the auth gate"


class TestRoleAuthorization:

    def test_registrar_cannot_create_election(self, api,
                                              registrar_clerk_headers):
        """PRD §4: 'POST /elections — ... Authorized Role(s):
        ElectionBoard.'
        PRD §2.1: 'A request whose role is not authorised for the
        targeted endpoint is rejected with ERR_FORBIDDEN.'

        Claim: RegistrarClerk POST /elections → ERR_FORBIDDEN.
        """
        resp = api.create_election(
            create_election_payload(), registrar_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_voter_cannot_advance_clock(self, api, voter_headers):
        """PRD §4: 'POST /_clock/advance — ... Authorized Role(s):
        TestDriver.'
        PRD §2.5: 'advancing it is reserved for TestDriver.'

        Claim: Voter POST /_clock/advance → ERR_FORBIDDEN.
        """
        resp = api.advance_clock(
            {"to_instant": "2030-01-01T00:00:00.000Z"}, voter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_precinct_officer_cannot_create_election(
            self, api, precinct_officer_headers):
        """PRD §4: 'POST /elections — ... Authorized Role(s):
        ElectionBoard.'

        Claim: PrecinctOfficer POST /elections → ERR_FORBIDDEN.
        """
        resp = api.create_election(
            create_election_payload(), precinct_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestEnvelope:

    def test_create_election_success_envelope(
            self, api, election_board_headers):
        """PRD §2.2: 'All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body.'

        Claim: meta has api_request_id (starts with 'req_') +
        api_request_timestamp, response_type='object', data is the
        Election row.
        """
        resp = api.create_election(
            create_election_payload(), election_board_headers,
        )
        body = resp.json()
        assert resp.status_code == 201
        assert "meta" in body and "response_type" in body
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert meta.get("api_request_id", "").startswith("req_"), (
            f"api_request_id must start with 'req_', "
            f"got {meta.get('api_request_id')!r}"
        )
        assert "api_request_timestamp" in meta
        assert isinstance(body["data"], dict) and body["data"].get("id")

    def test_error_envelope_includes_error_id_and_message(
            self, api, registrar_clerk_headers):
        """PRD §2.2: 'The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong.'
        """
        resp = api.create_election(
            create_election_payload(), registrar_clerk_headers,
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_FORBIDDEN.value
        assert isinstance(body["data"].get("message"), str)


class TestPathExistence:
    """PRD §2.7 — nested resource retrieval and left-to-right
    validation."""

    def test_nonexistent_election_returns_not_found(
            self, api, election_board_headers):
        """PRD §2.7: 'When an endpoint path contains multiple resource
        identifiers ... The first missing identifier produces
        ERR_NOT_FOUND immediately, before any deeper identifier is
        checked.'

        Claim: GET on an unknown electionId returns ERR_NOT_FOUND.
        """
        resp = api.get_election(NON_EXISTENT_UUID, election_board_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_precinct_under_nonexistent_election_reports_election_missing(
            self, api, election_board_headers):
        """PRD §2.7: 'A request for a precinct under a non-existent
        election therefore reports the election as missing rather than
        the precinct.'

        Claim: GET /elections/{bad}/precincts/{bad} → ERR_NOT_FOUND.
        """
        resp = api.get_precinct(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            election_board_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestPagination:

    def test_list_elections_returns_pagination_meta(
            self, api, election_board_headers):
        """PRD §2.3: 'Paginated list responses include the following
        fields in the meta object of the response envelope: limit,
        offset, total_count, and has_more.'
        """
        # Ensure at least one election exists.
        setup_election_with_precinct()
        resp = api.list_elections(election_board_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert isinstance(data, list)

    def test_list_elections_default_limit_is_10(
            self, api, election_board_headers):
        """PRD §2.3: 'The limit parameter specifies the maximum number
        of items to return; it defaults to 10.'
        """
        resp = api.list_elections(election_board_headers)
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"default limit must be 10 per PRD §2.3, got {meta['limit']}"
        )
