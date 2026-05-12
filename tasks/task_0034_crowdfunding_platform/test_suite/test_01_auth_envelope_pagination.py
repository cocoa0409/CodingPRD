"""Auth, RBAC, envelope, pagination, and path-existence checks.

PRD references:
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure
  - §2.3 Pagination
  - §2.6 Nested Resource Path Resolution
  - §2.8 Validation Ordering
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_backer_payload,
    create_initiator_payload,
    create_project_payload,
    setup_live_project,
    setup_revision_loop_project,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request
        is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-ID → ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api.create_initiator(create_initiator_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request
        is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-Role → ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "admin-001"}
        res = api.create_initiator(create_initiator_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request
        is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: empty X-User-ID → ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "", "X-User-Role": "PlatformAdmin"}
        res = api.create_initiator(create_initiator_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_no_headers_rejected(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request
        is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: no auth headers at all → ERR_AUTH_REQUIRED.
        """
        res = api.create_initiator(create_initiator_payload(), {})
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 — RBAC (forbidden role)
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["Backer", "ContentReviewer", "LegalReviewer",
         "FinancialReviewer", "PlatformAdmin"],
    )
    def test_create_project_requires_initiator_role(self, api, role):
        """PRD §2.1: 'When the headers are present but the role is not
        authorized for the endpoint, the request is rejected with
        ERR_FORBIDDEN (HTTP 403).'
        PRD §4: 'POST /projects ... Authorized Role(s): Initiator'.

        Claim: non-Initiator roles cannot create a project → ERR_FORBIDDEN.
        """
        headers = build_user_headers(f"u-{role}", role)
        res = api.create_project(create_project_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    @pytest.mark.parametrize(
        "role",
        ["Initiator", "Backer", "ContentReviewer", "LegalReviewer",
         "FinancialReviewer"],
    )
    def test_verify_kyc_requires_platform_admin(self, api, role):
        """PRD §4: 'POST /initiators/{id}/verify-kyc ... Authorized Role(s):
        PlatformAdmin'.
        PRD §2.1: 'When the headers are present but the role is not
        authorized for the endpoint, the request is rejected with
        ERR_FORBIDDEN (HTTP 403).'

        Claim: non-PlatformAdmin → ERR_FORBIDDEN on verify-kyc.
        """
        headers = build_user_headers(f"u-{role}", role)
        res = api.verify_kyc(
            "00000000-0000-0000-0000-000000000001",
            {"decision": "VERIFIED"},
            headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_review_content_requires_content_reviewer(
        self, api, legal_reviewer_headers,
    ):
        """PRD §4: 'POST /projects/{id}/review-content ... Authorized
        Role(s): ContentReviewer'.

        Claim: LegalReviewer cannot run content review → ERR_FORBIDDEN.
        """
        # Use a non-existent project id; RBAC fires before path-existence
        # per PRD §2.8 ('header presence ..., then role authorization,
        # then path-parameter existence').
        res = api.review_content(
            NON_EXISTENT_UUID, {"decision": "APPROVE"}, legal_reviewer_headers
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 — Success envelope
# ===========================================================================
class TestSuccessEnvelope:
    def test_create_initiator_envelope(self, api, platform_admin_headers):
        """PRD §2.2: 'All successful API responses ... follow this standard
        envelope format in their JSON body' with meta.api_request_id /
        api_request_timestamp / response_type / data.

        Claim: 201 envelope has the four canonical fields.
        """
        res = api.create_initiator(
            create_initiator_payload(), platform_admin_headers
        )
        # validate_success returns data and asserts status + envelope.
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict)
        assert "id" in data and isinstance(data["id"], str)
        body = res.json()
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: 'The api_request_id is a server-generated unique "
            "identifier for the request that starts with req_.'"
        )
        assert isinstance(meta.get("api_request_timestamp"), str)


# ===========================================================================
# §2.2 — Error envelope shape
# ===========================================================================
class TestErrorEnvelope:
    def test_error_response_has_error_id_and_message(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: '{"error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
        "message": "A human-readable explanation of the error."}'.

        Claim: error responses carry both error_id and message strings.
        """
        bad = {}
        res = api.create_initiator(create_initiator_payload(), bad)
        body = res.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


# ===========================================================================
# §2.3 — Pagination defaults and bounds
# ===========================================================================
class TestPagination:
    def test_list_projects_default_limit_and_meta_keys(
        self, api, platform_admin_headers,
    ):
        """PRD §2.3: 'The default limit is 10' and 'The pagination block in
        meta carries four values for every list response: limit, offset,
        total_count, has_more'.

        Claim: GET /projects without limit returns limit=10 in meta and
        all four pagination keys.
        """
        res = api.list_projects(platform_admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta and isinstance(meta["total_count"], int)
        assert "has_more" in meta and isinstance(meta["has_more"], bool)

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 200])
    def test_list_projects_limit_out_of_range(
        self, api, platform_admin_headers, bad_limit,
    ):
        """PRD §2.3: 'with a minimum of 1 and a maximum of 100; values
        outside this range are rejected.'

        Claim: limit < 1 or > 100 → 4xx error.
        """
        res = api.list_projects(
            platform_admin_headers, params={"limit": bad_limit}
        )
        # PRD §2.3 says values are 'rejected' but does not pin a specific
        # error_id. Per PRD-First, only assert HTTP 4xx.
        assert 400 <= res.status_code < 500


# ===========================================================================
# §2.6 — Nested resource path resolution (left-to-right)
# ===========================================================================
class TestNestedPathResolution:
    def test_unknown_project_id_on_rewards_returns_not_found(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: 'the leftmost identifier (typically project_id) is
        checked first; if it does not name an existing project, the
        request is rejected with ERR_NOT_FOUND (HTTP 404) without
        examining the next identifier.'

        Claim: GET /projects/{bad}/rewards → ERR_NOT_FOUND.
        """
        res = api.list_rewards(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_cross_project_reward_on_create_order_rejected(
        self, api,
    ):
        """PRD §2.6: 'A child whose parent reference does not match the URL
        parent is treated as a referential-integrity error and rejected
        with ERR_CROSS_PROJECT_REFERENCE (HTTP 422); this applies to
        reward CRUD and to order creation or modification where the
        selected reward, or any add-on referenced through add_on_item_id
        in add_ons, must belong to the order's project_id.'

        Claim: order pinning a reward from a different project →
        ERR_CROSS_PROJECT_REFERENCE.
        """
        from test_helpers import (
            create_backer,
            create_order_payload,
            make_backer_headers,
        )
        # Build two LIVE projects with their own rewards; pin Project A's
        # reward into a Project B order.
        _, project_a, reward_a = setup_live_project(
            category="TECH", funding_target_cents=10_000,
            reward_pledge_cents=5_000, reward_type="DIGITAL",
        )
        _, project_b, reward_b = setup_live_project(
            category="TECH", funding_target_cents=10_000,
            reward_pledge_cents=5_000, reward_type="DIGITAL",
        )
        backer = create_backer()
        payload = create_order_payload(
            project_id=project_b["id"],
            reward_id=reward_a["id"],  # belongs to project_a
        )
        res = api.create_order(payload, make_backer_headers(backer["id"]))
        validate_error(res, "ERR_CROSS_PROJECT_REFERENCE")


# ===========================================================================
# §2.8 — Validation ordering: header presence wins over RBAC and existence
# ===========================================================================
class TestValidationOrdering:
    def test_missing_headers_beat_unknown_path(self, api):
        """PRD §2.8: 'The order is: header presence (ERR_AUTH_REQUIRED),
        then role authorization (ERR_FORBIDDEN), then path-parameter
        existence (ERR_NOT_FOUND)'.

        Claim: a missing-headers request to a 404 path still returns
        ERR_AUTH_REQUIRED, not ERR_NOT_FOUND.
        """
        res = api.get_project(NON_EXISTENT_UUID, {})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_role_forbidden_beats_unknown_path(self, api):
        """PRD §2.8: 'The order is: header presence ..., then role
        authorization (ERR_FORBIDDEN), then path-parameter existence
        (ERR_NOT_FOUND)'.

        Claim: an authenticated but unauthorized role hitting a 404 path
        returns ERR_FORBIDDEN, not ERR_NOT_FOUND.
        """
        headers = build_user_headers("u1", "Backer")  # Backer cannot verify-kyc
        res = api.verify_kyc(
            NON_EXISTENT_UUID, {"decision": "VERIFIED"}, headers
        )
        validate_error(res, "ERR_FORBIDDEN")
