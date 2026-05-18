"""Auth headers, role-based access control, response envelope shape.

PRD §2.1 (auth) and §2.2 (envelope) and §2.3 (pagination).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_member_payload,
    create_unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header, carrying a
        malformed value, or naming a role outside this enumeration are
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: GET with no headers → ERR_UNAUTHENTICATED.
        """
        resp = api._request("GET", "/hoa/liens", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header, carrying a
        malformed value, or naming a role outside this enumeration are
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."
        """
        resp = api._request(
            "GET", "/hoa/liens",
            headers={"X-User-Role": "PresidentRole"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header, carrying a
        malformed value, or naming a role outside this enumeration are
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."
        """
        resp = api._request(
            "GET", "/hoa/liens",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Requests missing either header, carrying a
        malformed value, or naming a role outside this enumeration are
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: a role string outside the five-value catalog yields
        ERR_UNAUTHENTICATED.
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request("GET", "/hoa/liens", headers=bad_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize("role", [
        "Member", "SecretaryRole", "TreasurerRole",
        "PresidentRole", "DirectorRole",
    ])
    def test_each_of_five_roles_is_accepted_at_auth_stage(self, api, role):
        """PRD §2.1: "The role value MUST be one of the five strings:
        Member, SecretaryRole, TreasurerRole, PresidentRole, or
        DirectorRole."

        Claim: each of the five accepted role values clears the auth
        gate — a 401 (if any) is NOT ERR_UNAUTHENTICATED. The endpoint
        may yet return some other error (e.g., ERR_FORBIDDEN), but the
        auth catalog check passes.
        """
        headers = build_user_headers(f"user-{role.lower()}", role)
        resp = api._request("GET", "/hoa/liens", headers=headers)
        if resp.status_code == 401:
            body = resp.json().get("data", {}) or {}
            assert body.get("error_id") != (
                ApiErrorId.ERR_UNAUTHENTICATED.value
            ), f"role {role!r} should clear the 401/ERR_UNAUTHENTICATED gate"


class TestRoleAuthorization:

    def test_member_cannot_create_unit(self, api, member_headers):
        """PRD §4: "POST /hoa/units" — Authorized Role(s): PresidentRole.
        PRD §2.1: "A request whose role is well-formed but not permitted
        to invoke the requested endpoint is rejected with ERR_FORBIDDEN
        (HTTP 403)."

        Claim: Member POST /hoa/units → ERR_FORBIDDEN.
        """
        # The exact id is irrelevant — RBAC fires before any business
        # check that would consult it.
        resp = api.create_unit(
            create_unit_payload(
                owner_member_id=NON_EXISTENT_UUID, share_factor=1.0000,
            ),
            member_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_treasurer_cannot_create_member(self, api, treasurer_role_headers):
        """PRD §4: "POST /hoa/members" — Authorized Role(s): PresidentRole.

        Claim: TreasurerRole POST /hoa/members → ERR_FORBIDDEN.
        """
        resp = api.create_member(
            create_member_payload(), treasurer_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_director_cannot_advance_clock(self, api, director_role_headers):
        """PRD §4: "POST /hoa/_clock/advance" — Authorized Role(s):
        PresidentRole. PRD §3.10: "The clock-advance capability is
        exclusive to the PresidentRole."

        Claim: DirectorRole POST /_clock/advance → ERR_FORBIDDEN.
        """
        resp = api.advance_clock(
            {"target_timestamp": "2099-01-01T00:00:00.000Z"},
            director_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_member_cannot_create_assessment_cycle(self, api, member_headers):
        """PRD §4: "POST /hoa/assessment-cycles" — Authorized Role(s):
        TreasurerRole.

        Claim: Member POST /hoa/assessment-cycles → ERR_FORBIDDEN.
        """
        resp = api.create_assessment_cycle(
            {
                "cycle_type": "REGULAR",
                "period_start": "2026-01-01T00:00:00.000Z",
                "due_date": "2026-02-01T00:00:00.000Z",
                "total_levy_cents": 1000,
            },
            member_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_treasurer_cannot_create_violation(
        self, api, treasurer_role_headers,
    ):
        """PRD §4: "POST /hoa/violations" — Authorized Role(s):
        SecretaryRole, PresidentRole.

        Claim: TreasurerRole POST /hoa/violations → ERR_FORBIDDEN.
        """
        resp = api.create_violation(
            {"unit_id": NON_EXISTENT_UUID, "description": "x"},
            treasurer_role_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestResponseEnvelope:

    def test_success_envelope_has_meta_and_data(self, api,
                                                president_role_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta.api_request_id, meta.api_request_timestamp,
        response_type, data.

        Claim: a successful list call exposes the envelope keys.
        """
        resp = api.list_liens(president_role_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body, f"missing meta key in {body}"
        assert "response_type" in body
        assert "data" in body
        assert isinstance(body["meta"], dict)
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_; "
            f"got {body['meta']['api_request_id']!r}"
        )
        assert "api_request_timestamp" in body["meta"]

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: "data: { error_id ... message ... }" for error
        envelopes.

        Claim: error responses carry data.error_id and data.message.
        """
        resp = api._request("GET", "/hoa/liens", headers={})
        body = resp.json()
        assert body["response_type"] == "error", (
            f"expected response_type=error, got "
            f"{body.get('response_type')!r}"
        )
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)


class TestPaginationDefaults:

    def test_list_liens_paginated_meta_has_limit_offset_total_count_has_more(
        self, api, president_role_headers,
    ):
        """PRD §2.3: "The meta block on every list response carries
        limit, offset, total_count ..., and the boolean has_more
        indicating whether further pages exist beyond the current
        window."

        Claim: list /hoa/liens exposes the four pagination keys.
        """
        resp = api.list_liens(president_role_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"missing {key!r} in {meta}"
        assert isinstance(meta["has_more"], bool)

    def test_limit_defaults_to_ten_when_unspecified(
        self, api, president_role_headers,
    ):
        """PRD §2.3: "limit defaults to 10".

        Claim: when limit is not supplied, meta.limit == 10.
        """
        resp = api.list_liens(president_role_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"default limit should be 10 per PRD §2.3; got {meta['limit']}"
        )
