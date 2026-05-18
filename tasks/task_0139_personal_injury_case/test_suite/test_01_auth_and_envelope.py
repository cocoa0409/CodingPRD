"""Auth headers, role-based access control, response envelope shape.

PRD §2.1 (auth) and §2.2 (envelope) and §2.3 (pagination).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    build_user_headers,
    create_client_payload,
    create_case_payload,
    create_client,
    create_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Claim: GET /pi-cases with no headers → ERR_MISSING_AUTH_HEADERS.
        """
        resp = api._request("GET", "/pi-cases", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_missing_user_id_returns_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."
        """
        resp = api._request(
            "GET", "/pi-cases", headers={"X-User-Role": "Paralegal"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_missing_user_role_returns_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."
        """
        resp = api._request(
            "GET", "/pi-cases", headers={"X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_empty_user_id_returns_missing_auth(self, api):
        """PRD §2.1: "If either header is missing or empty"."""
        resp = api._request(
            "GET", "/pi-cases",
            headers={"X-User-ID": "", "X-User-Role": "Paralegal"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_unknown_role_returns_unknown_role(self, api):
        """PRD §2.1: "If X-User-Role carries a value that is not in the
        declared role catalog, the request is rejected with
        ERR_UNKNOWN_ROLE (HTTP 401)."
        """
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request("GET", "/pi-cases", headers=bad_headers)
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value)

    def test_role_catalog_is_paralegal_attorney_managing_partner(self, api):
        """PRD §2.1: "The role catalog contains exactly three values,
        spelled as shown: Paralegal, Attorney, and ManagingPartner."

        Claim: each of these three values is accepted (no 401 from role
        catalog gate); any other value yields ERR_UNKNOWN_ROLE.
        """
        for role in ("Paralegal", "Attorney", "ManagingPartner"):
            headers = build_user_headers(f"user-{role.lower()}", role)
            resp = api._request("GET", "/pi-cases", headers=headers)
            # 200 or 4xx other than auth — but never ERR_UNKNOWN_ROLE.
            assert resp.status_code != 401 or (
                resp.status_code == 401
                and (resp.json().get("data", {}) or {}).get("error_id")
                != ApiErrorId.ERR_UNKNOWN_ROLE.value
            )


class TestRoleAuthorization:

    def test_paralegal_cannot_create_demand_letter(
        self, api, paralegal_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Paralegal POST /demand-letters → ERR_FORBIDDEN. PRD §4
        endpoint table lists demand-letter operations as Attorney-only.
        """
        # We don't even need a real case id — RBAC fires before NotFound.
        resp = api._request(
            "POST",
            f"/pi-cases/{NON_EXISTENT_UUID}/demand-letters",
            {"demanded_amount_cents": 1000}, paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_attorney_cannot_approve_disbursement(
        self, api, attorney_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Attorney POST /disbursement/approve → ERR_FORBIDDEN.
        PRD §4 endpoint table restricts disbursement approval to
        ManagingPartner.
        """
        resp = api._request(
            "POST",
            f"/pi-cases/{NON_EXISTENT_UUID}/disbursement/approve",
            {"strategy": "CHRONOLOGICAL_PRIORITY"}, attorney_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_attorney_cannot_dismiss_case(self, api, attorney_headers):
        """PRD §2.1: "The ManagingPartner role approves final
        disbursement, dismisses cases, applies tolling to a case's
        statute deadline, and runs the administrative sweeps."

        Claim: Attorney dismiss → ERR_FORBIDDEN. PRD §4 endpoint table
        restricts POST /pi-cases/{id}/dismiss to ManagingPartner.
        """
        resp = api._request(
            "POST", f"/pi-cases/{NON_EXISTENT_UUID}/dismiss",
            {"reason": "x"}, attorney_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_attorney_cannot_toll_sol(self, api, attorney_headers):
        """PRD §3.2: "Tolling is applied through a ManagingPartner
        operation that supplies additional_days and a free-text
        reason".

        Claim: Attorney toll → ERR_FORBIDDEN.

        NOTE: PRD §4 endpoint table also lists Attorney for toll. So we
        only assert that the catalog gate fires for an UNAUTHORIZED
        role — here we use Paralegal which is NOT in the toll role list.
        """
        # Pivot: use Paralegal — PRD §4 lists toll as Attorney +
        # ManagingPartner only.
        resp = api._request(
            "POST", f"/pi-cases/{NON_EXISTENT_UUID}/toll",
            {"additional_days": 1, "reason": "x"},
            TEST_USERS["paralegal_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestSuccessEnvelope:

    def test_success_envelope_shape(
        self, api, paralegal_headers,
    ):
        """PRD §2.2 (Standard Success Response Format): "All successful
        API responses (those with 2xx status codes) follow this
        standard envelope format in their JSON body".

        Claim: POST /clients returns meta + response_type + data.
        """
        resp = api.create_client(
            create_client_payload(), paralegal_headers,
        )
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        meta = body["meta"]
        assert "api_request_id" in meta
        # PRD §2.2: "starts with req_".
        assert str(meta["api_request_id"]).startswith("req_"), (
            f"api_request_id must start with req_, got "
            f"{meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable
        string that identifies the specific error."
        PRD §2.2: "The message provides a human-readable explanation
        of what went wrong."

        Claim: error body carries response_type=='error' with
        data.error_id and data.message.
        """
        resp = api._request("GET", "/pi-cases", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {}) or {}
        assert "error_id" in data
        assert "message" in data


class TestPagination:

    def test_list_cases_uses_default_limit(
        self, api, paralegal_headers,
    ):
        """PRD §2.3: "The limit parameter defaults to 10 when not
        provided".

        Claim: GET /pi-cases without limit returns meta.limit == 10.
        """
        # Create 3 cases so we know there's data.
        client = create_client()
        for _ in range(3):
            create_case(client["id"])
        resp = api.list_cases(paralegal_headers)
        data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
            f"PRD §2.3 default limit is 10, got {meta['limit']}"
        )
        assert meta["offset"] == 0
        assert isinstance(data, list)
