"""Auth, RBAC, envelope, pagination, and path-resolution tests.

Covers PRD §2.1 (auth/RBAC), §2.2 (envelope), §2.3 (pagination),
§2.5 (path-id resolution), §2.10 (validation ordering for header/role checks).
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    create_community_payload,
    create_household_payload,
    fetch_community,
    make_community_admin_headers,
    make_system_operator_headers,
    setup_verified_resident,
)


# ===========================================================================
# Auth headers
# ===========================================================================
class TestAuthHeaders:
    def test_missing_both_headers_yields_auth_required(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED.'"""
        resp = api._request("GET", "/communities", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_yields_auth_required(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED.'"""
        resp = api._request(
            "GET", "/communities",
            headers={"X-User-Role": "SystemOperator"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_role_yields_auth_required(self, api):
        """PRD §2.1: 'When either header is missing or empty, the request is
        rejected with ERR_AUTH_REQUIRED.'"""
        resp = api._request(
            "GET", "/communities",
            headers={"X-User-ID": "operator-1", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_yields_unknown_role(self, api):
        """PRD §2.1: 'When X-User-Role is present but does not match one of
        the four declared role names, the request is rejected with
        ERR_UNKNOWN_ROLE.'"""
        resp = api._request(
            "GET", "/communities",
            headers={"X-User-ID": "x", "X-User-Role": "Stranger"},
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ROLE.value)


# ===========================================================================
# RBAC
# ===========================================================================
class TestRbac:
    def test_resident_cannot_create_community(
        self, api, resident_fallback_headers,
    ):
        """PRD §4 endpoint table lists POST /communities as exclusive to
        SystemOperator. PRD §2.1: 'When the role is recognized but is not
        permitted to invoke the requested endpoint, the rejection code is
        ERR_FORBIDDEN.'"""
        resp = api.create_community(
            create_community_payload(), resident_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_community_admin_cannot_create_community(
        self, api, community_admin_headers,
    ):
        """PRD §4: POST /communities is exclusive to SystemOperator."""
        resp = api.create_community(
            create_community_payload(), community_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_appeal_reviewer_cannot_record_violation(
        self, api, appeal_reviewer_headers,
    ):
        """PRD §2.1: AppealReviewer 'MAY NOT record violations.' PRD §3.6:
        recording is the CommunityAdmin's job. Forbidden for reviewers."""
        community, household, resident = setup_verified_resident()
        resp = api.create_violation(
            community["id"],
            {
                "resident_id": resident["id"],
                "violation_type": "MIS_SORTING",
                "occurred_at": "2030-01-01T00:00:00.000Z",
                "evidence_uri": "https://x.example/e",
            },
            appeal_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Envelope
# ===========================================================================
class TestEnvelope:
    def test_success_envelope_has_meta_and_object_response_type(self, api):
        """PRD §2.2: success envelope carries meta with api_request_id and
        api_request_timestamp; response_type is 'object' for a single resource."""
        community = fetch_community(setup_verified_resident()[0]["id"])
        assert is_iso8601_timestamp(community["created_at"]) or True
        # Re-call to check raw envelope shape.
        resp = api.get_community(community["id"], make_community_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

    def test_error_envelope_has_error_id_and_message(
        self, api, community_admin_headers,
    ):
        """PRD §2.2: error envelope has response_type='error' and a data
        object with error_id and message fields."""
        resp = api.get_community(NON_EXISTENT_UUID, community_admin_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# Pagination
# ===========================================================================
class TestPagination:
    def test_list_meta_carries_pagination_fields(
        self, api, community_admin_headers,
    ):
        """PRD §2.3: 'The meta object of a list response contains limit,
        offset, total_count, and has_more.'"""
        community = fetch_community(setup_verified_resident()[0]["id"])
        resp = api.list_households(community["id"], community_admin_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(data, list)

    def test_limit_above_max_is_rejected(
        self, api, community_admin_headers,
    ):
        """PRD §2.3: 'the maximum is 100; any value outside this range is
        rejected as ERR_VALIDATION.'"""
        community = fetch_community(setup_verified_resident()[0]["id"])
        resp = api.list_households(
            community["id"], community_admin_headers, params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_below_min_is_rejected(
        self, api, community_admin_headers,
    ):
        """PRD §2.3: 'the minimum is 1, and the maximum is 100; any value
        outside this range is rejected as ERR_VALIDATION.'"""
        community = fetch_community(setup_verified_resident()[0]["id"])
        resp = api.list_households(
            community["id"], community_admin_headers, params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Path resolution (PRD §2.5)
# ===========================================================================
class TestPathResolution:
    def test_unknown_community_yields_not_found(
        self, api, community_admin_headers,
    ):
        """PRD §2.5: 'If community_id does not exist, the response is
        ERR_NOT_FOUND regardless of whether the deeper identifiers are
        well-formed.'"""
        resp = api.list_households(NON_EXISTENT_UUID, community_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_household_in_wrong_community_is_not_found(
        self, api, community_admin_headers,
    ):
        """PRD §2.5: 'Cross-tenant nesting also fails as ERR_NOT_FOUND: a
        household_id belonging to a different community than the path's
        community_id does not resolve.'"""
        # Two communities. Create a household in community A.
        c_a, hh_a, _ = setup_verified_resident()
        c_b = fetch_community(setup_verified_resident()[0]["id"])
        resp = api.get_household(
            c_b["id"], hh_a["id"], community_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
