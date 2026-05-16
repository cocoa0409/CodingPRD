"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.8):
- Missing X-User-Role / X-User-ID header -> ERR_AUTH_MISSING (401).
- Unrecognized X-User-Role -> ERR_AUTH_INVALID_ROLE (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Response envelope shape (success / error).
- Pagination parameters limit/offset bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    create_beneficiary_payload,
    create_plan_payload,
    setup_clock_at,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'A request missing either header is rejected with
    ERR_AUTH_MISSING and HTTP 401.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Every request to the API must carry two HTTP
        headers: X-User-ID (an opaque per-request identifier) and
        X-User-Role (one of the four enumerated roles). A request
        missing either header is rejected with ERR_AUTH_MISSING and
        HTTP 401."

        Claim: omitting both auth headers -> ERR_AUTH_MISSING / 401.
        """
        resp = api._request("GET", "/plans", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_MISSING and HTTP 401."

        Claim: missing X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/plans", headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_AUTH_MISSING and HTTP 401."

        Claim: missing X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/plans", headers={"X-User-Role": "PlanAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Invalid role — PRD §2.1
# ===========================================================================
class TestAuthInvalidRole:
    """PRD §2.1: 'A request whose role does not match one of the four
    enumerated values is rejected with ERR_AUTH_INVALID_ROLE and HTTP
    401.'"""

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Counselor", "OperationsManager", ""],
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "A request whose role does not match one of the
        four enumerated values is rejected with ERR_AUTH_INVALID_ROLE
        and HTTP 401."

        Claim: unrecognized X-User-Role -> ERR_AUTH_INVALID_ROLE / 401.
        """
        resp = api._request(
            "GET", "/plans",
            headers={"X-User-Role": bad_role, "X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# RBAC enforcement — PRD §2.1
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'A request whose role is recognised but lacks
    permission for the targeted endpoint is rejected with ERR_FORBIDDEN
    and HTTP 403.'"""

    def test_counselor_cannot_create_beneficiary(self, api,
                                                 counselor_headers):
        """PRD §4: "POST /beneficiaries — Authorized Role(s): PlanAdmin"
        and PRD §2.1: "A request whose role is recognised but lacks
        permission for the targeted endpoint is rejected with
        ERR_FORBIDDEN and HTTP 403."

        Claim: BenefitsCounselor cannot POST /beneficiaries.
        """
        setup_clock_at(2026, 1, 1)
        resp = api.create_beneficiary(
            create_beneficiary_payload(), counselor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_counselor_cannot_create_plan(self, api, counselor_headers):
        """PRD §4: "POST /plans — Authorized Role(s): PlanAdmin".

        Claim: BenefitsCounselor cannot POST /plans -> ERR_FORBIDDEN /
        HTTP 403.
        """
        resp = api.create_plan(
            create_plan_payload(), counselor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_advance_clock(self, api, auditor_headers,
                                          admin_headers):
        """PRD §4: "POST /_clock/advance — Authorized Role(s): PlanAdmin,
        Auditor". This endpoint permits Auditor too, so it must succeed.

        Conversely, Beneficiary role cannot. This test checks the
        positive case to prevent over-restrictive RBAC; the Beneficiary
        negative case is below.
        """
        resp = api.clock_advance(
            {"to": "2026-01-01T00:00:00.000Z"}, auditor_headers,
        )
        validate_success(resp)

    def test_beneficiary_cannot_advance_clock(self, api,
                                              beneficiary_fallback_headers):
        """PRD §4: "POST /_clock/advance — Authorized Role(s): PlanAdmin,
        Auditor". Beneficiary role is NOT in that list and PRD §2.1:
        "A request whose role is recognised but lacks permission for
        the targeted endpoint is rejected with ERR_FORBIDDEN and HTTP
        403."

        Claim: Beneficiary cannot POST /_clock/advance.
        """
        resp = api.clock_advance(
            {"to": "2026-01-01T00:00:00.000Z"},
            beneficiary_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_create_plan(self, api, auditor_headers):
        """PRD §4: "POST /plans — Authorized Role(s): PlanAdmin".

        Claim: Auditor (read-only oversight) cannot POST /plans.
        PRD §2.1: "Auditor — Read-only oversight; sees all
        beneficiaries' data but cannot mutate any resource."
        """
        resp = api.create_plan(create_plan_payload(), auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2 success envelope shape."""

    def test_get_clock_returns_object_envelope(self, api, admin_headers):
        """PRD §2.2: "The response_type is either 'object' for a single
        resource or 'array' for a list of resources."

        Claim: GET /_clock returns response_type='object' with a 'data'
        payload.
        """
        resp = api.get_clock(admin_headers)
        data = validate_success(resp)
        assert "now" in data

    def test_list_plans_returns_paginated_envelope(self, api,
                                                   admin_headers):
        """PRD §2.3: "the response meta carries limit, offset,
        total_count, and has_more so that clients can detect the end of
        a page sequence without an extra call."

        Claim: GET /plans returns a paginated envelope.
        """
        resp = api.list_plans(admin_headers, params={"limit": 10})
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPaginationBounds:
    """PRD §2.3 limit/offset bounds."""

    def test_limit_zero_rejected(self, api, admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside this band are rejected with
        ERR_VALIDATION."

        Claim: limit=0 -> ERR_VALIDATION.
        """
        resp = api.list_plans(admin_headers, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_over_max_rejected(self, api, admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside this band are rejected with
        ERR_VALIDATION."

        Claim: limit=101 -> ERR_VALIDATION.
        """
        resp = api.list_plans(admin_headers, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_boundary_min_accepted(self, api, admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside this band are rejected with
        ERR_VALIDATION."

        Claim: limit=1 (lower boundary) is accepted.
        """
        resp = api.list_plans(admin_headers, params={"limit": 1})
        validate_paginated(resp)

    def test_limit_boundary_max_accepted(self, api, admin_headers):
        """PRD §2.3: "limit defaults to 10, has a minimum of 1, and a
        maximum of 100; values outside this band are rejected with
        ERR_VALIDATION."

        Claim: limit=100 (upper boundary) is accepted.
        """
        resp = api.list_plans(admin_headers, params={"limit": 100})
        validate_paginated(resp)


# ===========================================================================
# Error envelope shape — PRD §2.2
# ===========================================================================
class TestErrorEnvelope:
    """PRD §2.2 error envelope shape."""

    def test_error_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: a 4xx response carries error_id and message in data.
        """
        resp = api._request("GET", "/plans", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)
