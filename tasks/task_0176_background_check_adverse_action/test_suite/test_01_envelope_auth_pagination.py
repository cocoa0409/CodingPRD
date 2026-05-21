"""Envelope, auth, role, pagination, and 404 probes.

These tests do not depend on domain workflow state. They probe the
cross-cutting rules from PRD §2.1 (auth + role), §2.2 (response
envelope), §2.3 (pagination), §2.6 (left-to-right path lookup).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_candidate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: "Every request to the API MUST include two headers:
    `X-User-ID`, identifying the calling principal, and `X-User-Role`,
    naming the role the principal is acting as. If either header is
    missing or empty, the request is rejected with `ERR_AUTH_REQUIRED`
    (HTTP 401)."
    """

    def test_missing_x_user_id_is_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_candidates({"X-User-Role": "Recruiter"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_x_user_role_is_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_candidates({"X-User-ID": "recruiter-1"})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_x_user_id_is_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

        Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_candidates(
            {"X-User-ID": "", "X-User-Role": "Recruiter"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_x_user_role_is_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with `ERR_AUTH_REQUIRED` (HTTP 401)."

        Claim: empty X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api.list_candidates(
            {"X-User-ID": "recruiter-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role authorization — PRD §2.1 + §4 endpoint table
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "If the role is not authorised for the endpoint per
    the matrix described in §4, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    """

    def test_candidate_cannot_create_candidate(
        self, api, candidate_headers,
    ):
        """PRD §4: "POST /fcra/candidates ... Recruiter" — only Recruiter
        may register candidates. PRD §2.1: "the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: Candidate POST /fcra/candidates -> ERR_FORBIDDEN.
        """
        resp = api.create_candidate(
            create_candidate_payload(), candidate_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_recruiter_cannot_issue_pre_adverse(
        self, api, recruiter_headers,
    ):
        """PRD §4: "POST /fcra/orders/{orderId}/pre-adverse ...
        Adjudicator". PRD §2.1: "the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Claim: Recruiter POST /pre-adverse -> ERR_FORBIDDEN.
        """
        resp = api.issue_pre_adverse(NON_EXISTENT_UUID, recruiter_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_recruiter_cannot_run_sweep(self, api, recruiter_headers):
        """PRD §4: "POST /fcra/_sweep/run ... PlatformAdmin". PRD §2.1:
        "the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: Recruiter POST /_sweep/run -> ERR_FORBIDDEN.
        """
        resp = api.run_sweep(recruiter_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_verifier_cannot_create_order(self, api, verifier_headers):
        """PRD §4: "POST /fcra/orders ... Recruiter". PRD §2.1: "the
        request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: Verifier POST /fcra/orders -> ERR_FORBIDDEN.
        """
        resp = api.create_order(
            {
                "candidate_id": NON_EXISTENT_UUID,
                "consent_disclosure_id": NON_EXISTENT_UUID,
                "stage_at_order": "PRE_OFFER",
                "requested_packages": ["CRIMINAL"],
            },
            verifier_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_platform_admin_cannot_create_order(
        self, api, platform_admin_headers,
    ):
        """PRD §4: "POST /fcra/orders ... Recruiter" — PlatformAdmin is
        not authorised. PRD §2.1: "the request is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Claim: PlatformAdmin POST /fcra/orders -> ERR_FORBIDDEN.
        """
        resp = api.create_order(
            {
                "candidate_id": NON_EXISTENT_UUID,
                "consent_disclosure_id": NON_EXISTENT_UUID,
                "stage_at_order": "PRE_OFFER",
                "requested_packages": ["CRIMINAL"],
            },
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path-id lookup — PRD §2.6
# ===========================================================================
class TestPathIdentifierLookup:
    """PRD §2.6: "If a referenced `Candidate` does not exist or has a
    non-null `archived_at`, the response is `ERR_CANDIDATE_NOT_FOUND`
    (HTTP 404). If a referenced `BackgroundCheckOrder` does not exist,
    the response is `ERR_ORDER_NOT_FOUND` (HTTP 404). For other
    resources reached by id — `VerificationItem`, `Dispute`,
    `ConsentDisclosure`, and `JurisdictionPolicy` — the response is
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    """

    def test_get_unknown_candidate_returns_candidate_not_found(
        self, api, recruiter_headers,
    ):
        """PRD §2.6: "If a referenced `Candidate` does not exist or has
        a non-null `archived_at`, the response is
        `ERR_CANDIDATE_NOT_FOUND` (HTTP 404)."

        Claim: GET /fcra/candidates/{unknown} -> ERR_CANDIDATE_NOT_FOUND.
        """
        resp = api.get_candidate(NON_EXISTENT_UUID, recruiter_headers)
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_FOUND.value)

    def test_get_unknown_order_returns_order_not_found(
        self, api, recruiter_headers,
    ):
        """PRD §2.6: "If a referenced `BackgroundCheckOrder` does not
        exist, the response is `ERR_ORDER_NOT_FOUND` (HTTP 404)."

        Claim: GET /fcra/orders/{unknown} -> ERR_ORDER_NOT_FOUND.
        """
        resp = api.get_order(NON_EXISTENT_UUID, recruiter_headers)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)

    def test_get_unknown_verification_item_returns_resource_not_found(
        self, api, recruiter_headers,
    ):
        """PRD §2.6: "For other resources reached by id —
        `VerificationItem`, `Dispute`, `ConsentDisclosure`, and
        `JurisdictionPolicy` — the response is `ERR_RESOURCE_NOT_FOUND`
        (HTTP 404)."

        Claim: GET /fcra/verification-items/{unknown} ->
        ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_verification_item(
            NON_EXISTENT_UUID, recruiter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_get_unknown_dispute_returns_resource_not_found(
        self, api, adjudicator_headers,
    ):
        """PRD §2.6: "For other resources reached by id —
        `VerificationItem`, `Dispute`, `ConsentDisclosure`, and
        `JurisdictionPolicy` — the response is `ERR_RESOURCE_NOT_FOUND`
        (HTTP 404)."

        Claim: GET /fcra/disputes/{unknown} -> ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_dispute(NON_EXISTENT_UUID, adjudicator_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success envelope carries meta.api_request_id (req_
    prefix), meta.api_request_timestamp (ISO 8601 UTC w/ 3 fractional
    digits), response_type ('object' | 'array'), and data."""

    def test_success_envelope_shape(self, api, platform_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: 2xx response has meta.api_request_id starting with 'req_'
        and meta.api_request_timestamp is present.
        """
        resp = api.list_jurisdiction_policies(platform_admin_headers)
        body = resp.json()
        meta = body["meta"]
        assert "api_request_id" in meta
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta
        assert body["response_type"] in ("object", "array")
        assert "data" in body

    def test_error_envelope_shape(self, api, recruiter_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... `response_type`: 'error' ...
        `error_id`: ... `message`: ..."

        Claim: 4xx response has response_type='error' and
        data.error_id + data.message present.
        """
        resp = api.get_candidate(NON_EXISTENT_UUID, recruiter_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_CANDIDATE_NOT_FOUND.value
        )
        assert isinstance(body["data"].get("message"), str)
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_")


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3 pagination defaults and bounds."""

    def test_default_limit_and_offset_on_list_candidates(
        self, api, recruiter_headers,
    ):
        """PRD §2.3: "The default `limit` is 10, the minimum is 1, and
        the maximum is 100; the default `offset` is 0. ... Each list
        response carries pagination state in `meta`: the echoed `limit`,
        the echoed `offset`, the `total_count` of records matching the
        filter set, and a `has_more` boolean".

        Claim: list endpoint responds with paginated envelope carrying
        limit/offset/total_count/has_more, with defaults 10/0.
        """
        resp = api.list_candidates(recruiter_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 10
        assert meta["offset"] == 0
