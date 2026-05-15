"""Authentication, role recognition, RBAC, and the response envelope.

Covers PRD §2.1 (auth headers and role recognition), §2.2 (envelope),
§2.3 (pagination), §2.5 (path-parameter existence), §2.6 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_district_payload,
    create_family_payload,
    create_district,
    is_iso8601_timestamp,
    setup_district_with_school_and_program,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_rejected_with_auth_missing(self, api):
        """PRD §2.1: "If either header is absent the request is rejected
        with ERR_AUTH_MISSING."

        Claim: omission of X-User-ID and X-User-Role on a non-trivial
        endpoint yields ERR_AUTH_MISSING.
        """
        res = api.create_district(create_district_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is absent the request is rejected
        with ERR_AUTH_MISSING."

        Claim: header presence is checked per-header, so omitting only
        X-User-ID still triggers ERR_AUTH_MISSING.
        """
        res = api.create_district(
            create_district_payload(), headers={"X-User-Role": "SystemOperator"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is absent the request is rejected
        with ERR_AUTH_MISSING."
        """
        res = api.create_district(
            create_district_payload(), headers={"X-User-ID": "anyone"},
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    @pytest.mark.parametrize("bad_role", ["Superuser", "admin", "Parent", "", "DISTRICT_ADMIN"])
    def test_unrecognized_role_rejected(self, api, bad_role):
        """PRD §2.1: "any value of X-User-Role outside this set is
        rejected with ERR_AUTH_INVALID_ROLE."

        Claim: roles outside {SystemOperator, DistrictAdmin, FamilyUser}
        yield ERR_AUTH_INVALID_ROLE.
        """
        headers = {"X-User-ID": "u", "X-User-Role": bad_role}
        res = api.create_district(create_district_payload(), headers=headers)
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# RBAC (PRD §2.1 + §4 table)
# ===========================================================================
class TestRBAC:

    def test_create_district_requires_system_operator(
        self, api, district_admin_fallback_headers,
    ):
        """PRD §4: "POST /enrollment/districts | ... | SystemOperator".

        Claim: DistrictAdmin is not authorized to POST /districts and
        receives ERR_FORBIDDEN.
        """
        res = api.create_district(create_district_payload(), district_admin_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_district_forbidden_for_family_user(
        self, api, family_user_fallback_headers,
    ):
        """PRD §4 RBAC table reserves POST /enrollment/districts for
        SystemOperator only. FamilyUser must receive ERR_FORBIDDEN.

        PRD §2.1: "If the role is recognized but not authorized for that
        endpoint, the request is rejected with ERR_FORBIDDEN."
        """
        res = api.create_district(create_district_payload(), family_user_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_clock_advance_forbidden_for_district_admin(
        self, api, district_admin_fallback_headers,
    ):
        """PRD §4: "POST /enrollment/_clock/advance | ... | SystemOperator".
        PRD §2.1: "If the role is recognized but not authorized for that
        endpoint, the request is rejected with ERR_FORBIDDEN."
        """
        res = api.advance_clock("2030-01-01T00:00:00.000Z", district_admin_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, system_operator_headers):
        """PRD §2.2: success responses include
        meta.api_request_id (starts with req_),
        meta.api_request_timestamp (ISO 8601 UTC with three fractional
        digits), response_type, and data.

        Claim: a 201 envelope obeys this shape, and api_request_id
        begins with the literal prefix "req_".
        """
        res = api.create_district(create_district_payload(), system_operator_headers)
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body and "response_type" in body and "data" in body
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), \
            "PRD §2.2: api_request_id must start with 'req_'"
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: error responses include
        meta.api_request_id, meta.api_request_timestamp,
        response_type == "error", and data.error_id + data.message.
        """
        res = api.create_district(create_district_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"] and "message" in body["data"]
        assert body["data"]["error_id"] == ApiErrorId.ERR_AUTH_MISSING.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ===========================================================================
# Pagination defaults (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_list_districts_default_pagination(self, api, system_operator_headers):
        """PRD §2.3: "the limit query parameter ... defaults to 10 ...
        offset ... defaults to 0."

        Claim: list with no params returns at most 10, and meta
        contains limit, offset, total_count, has_more.
        """
        for _ in range(3):
            api.create_district(create_district_payload(), system_operator_headers)
        data, meta = validate_paginated(api.list_districts(system_operator_headers))
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        assert len(data) <= 10

    def test_list_districts_custom_limit(self, api, system_operator_headers):
        """PRD §2.3: "limit ... with a minimum of 1 and a maximum of 100."

        Claim: limit=1 returns exactly one row when at least one exists;
        has_more reflects the count.
        """
        for _ in range(3):
            api.create_district(create_district_payload(), system_operator_headers)
        data, meta = validate_paginated(
            api.list_districts(system_operator_headers, params={"limit": 1}),
        )
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is True


# ===========================================================================
# Path-parameter existence (PRD §2.5)
# ===========================================================================
class TestExistence:

    def test_get_nonexistent_district_returns_not_found(self, api, system_operator_headers):
        """PRD §2.5: "The first identifier that does not resolve to an
        existing row causes the request to be rejected with
        ERR_NOT_FOUND."
        """
        res = api.get_district(NON_EXISTENT_UUID, system_operator_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_application(self, api, system_operator_headers):
        """PRD §2.5: ERR_NOT_FOUND for unresolvable path identifier."""
        res = api.get_application(NON_EXISTENT_UUID, system_operator_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_school_with_unknown_district_returns_fk_not_found(
        self, api,
    ):
        """PRD §2.5: "an unresolvable body foreign key is rejected with
        ERR_FK_NOT_FOUND and a 422 status."

        Acting role is DistrictAdmin whose X-User-ID equals the body's
        district_id — so the call is authorized but the FK target row
        does not exist.
        """
        # Use a fresh UUID that is BOTH the X-User-ID and the body
        # district_id, so ownership comparison passes (PRD §2.1) yet the
        # district itself does not exist and ERR_FK_NOT_FOUND is the
        # only legitimate outcome.
        ghost_id = NON_EXISTENT_UUID
        payload = {
            "district_id": ghost_id,
            "name": "Ghost School",
            "school_type": "NEIGHBORHOOD",
            "grade_levels_offered": [5],
        }
        res = api.create_school(payload, build_user_headers(ghost_id, "DistrictAdmin"))
        validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ===========================================================================
# Optimistic Concurrency Control (PRD §2.6)
# ===========================================================================
class TestOCC:

    def test_patch_district_with_stale_version_rejected(
        self, api, system_operator_headers,
    ):
        """PRD §2.6: "If the client supplies version and the value does
        not match the server's current version of the target resource,
        the request is rejected with ERR_VERSION_MISMATCH."

        Claim: PATCH with a stale version returns ERR_VERSION_MISMATCH
        (409).
        """
        district = create_district()
        v0 = district["version"]
        # First PATCH bumps version.
        first = api.patch_district(
            district["id"],
            {"poverty_index_threshold": 0.40, "version": v0},
            system_operator_headers,
        )
        updated = validate_success(first, 200)
        assert updated["version"] > v0
        # Second PATCH with the now-stale v0.
        res = api.patch_district(
            district["id"],
            {"poverty_index_threshold": 0.30, "version": v0},
            system_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_patch_without_version_skips_occ(self, api, system_operator_headers):
        """PRD §2.6: "If version is omitted, the server applies the
        mutation without an OCC check."

        Claim: PATCH without version succeeds and bumps version.
        """
        district = create_district()
        res = api.patch_district(
            district["id"],
            {"poverty_index_threshold": 0.42},
            system_operator_headers,
        )
        updated = validate_success(res, 200)
        assert updated["version"] > district["version"]
        assert updated["poverty_index_threshold"] == pytest.approx(0.42, abs=1e-9)
