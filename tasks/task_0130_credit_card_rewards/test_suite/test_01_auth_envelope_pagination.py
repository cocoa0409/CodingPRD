"""Authentication, RBAC, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.5):
- Missing X-User-Role / X-User-ID -> ERR_UNAUTHENTICATED (401).
- Unrecognized role -> ERR_UNAUTHENTICATED (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Response envelope shape (success / error).
- Pagination limit/offset bounds.
- Path-segment 404.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    clock_advance_payload,
    create_cardholder_payload,
    setup_clock_at,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'A request that omits either header, or that supplies a
    role string outside this enumeration, is rejected with
    ERR_UNAUTHENTICATED.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        X-User-ID identifying the acting principal, and X-User-Role
        identifying the role being exercised. The system recognises
        exactly two roles: Cardholder and PlatformAdmin. A request that
        omits either header, or that supplies a role string outside
        this enumeration, is rejected with ERR_UNAUTHENTICATED."

        Claim: omitting both auth headers -> ERR_UNAUTHENTICATED.
        """
        resp = api._request("GET", "/cashback-categories", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that
        supplies a role string outside this enumeration, is rejected
        with ERR_UNAUTHENTICATED."

        Claim: missing X-User-Role -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", "/cashback-categories",
            headers={"X-User-ID": "anybody"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that
        supplies a role string outside this enumeration, is rejected
        with ERR_UNAUTHENTICATED."

        Claim: missing X-User-ID -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", "/cashback-categories",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Unrecognized role — PRD §2.1
# ===========================================================================
class TestAuthInvalidRole:
    """PRD §2.1: 'or that supplies a role string outside this
    enumeration, is rejected with ERR_UNAUTHENTICATED.'"""

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "cardholder", "platformadmin", "Operator", ""],
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "The system recognises exactly two roles:
        Cardholder and PlatformAdmin. A request that omits either
        header, or that supplies a role string outside this enumeration,
        is rejected with ERR_UNAUTHENTICATED."

        Claim: unrecognized X-User-Role -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", "/cashback-categories",
            headers={"X-User-Role": bad_role, "X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# RBAC enforcement — PRD §2.1 & §4
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'A request that is authenticated but targets an
    endpoint not permitted to the supplied role per §4 is rejected with
    ERR_FORBIDDEN.'"""

    def test_cardholder_cannot_create_cardholder(
        self, api, cardholder_fallback_headers,
    ):
        """PRD §4: "POST /cardholders — Authorized Role(s):
        PlatformAdmin" and PRD §2.1: "A request that is authenticated
        but targets an endpoint not permitted to the supplied role per
        §4 is rejected with ERR_FORBIDDEN."

        Claim: Cardholder cannot POST /cardholders.
        """
        setup_clock_at(2026, 1, 2)
        resp = api.create_cardholder(
            create_cardholder_payload(), cardholder_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_cardholder_cannot_advance_clock(
        self, api, cardholder_fallback_headers,
    ):
        """PRD §4: "POST /_clock/advance — Authorized Role(s):
        PlatformAdmin".

        Claim: Cardholder cannot POST /_clock/advance -> ERR_FORBIDDEN.
        """
        resp = api.clock_advance(
            clock_advance_payload(to_timestamp="2026-02-01T00:00:00.000Z"),
            cardholder_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_cardholder_cannot_run_sweep(
        self, api, cardholder_fallback_headers,
    ):
        """PRD §4: "POST /_sweep/run — Authorized Role(s):
        PlatformAdmin".

        Claim: Cardholder cannot POST /_sweep/run -> ERR_FORBIDDEN.
        """
        resp = api.sweep_run(None, cardholder_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_cardholder_cannot_register_partner(
        self, api, cardholder_fallback_headers,
    ):
        """PRD §4: "POST /transfer-partners — Authorized Role(s):
        PlatformAdmin".

        Claim: Cardholder cannot POST /transfer-partners.
        """
        resp = api._request(
            "POST", "/transfer-partners",
            {
                "code": "AIR_TEST",
                "partner_type": "AIRLINE",
                "conversion_ratio_points_per_unit": 2,
                "min_transfer_increment": 1000,
            },
            cardholder_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2 success envelope shape."""

    def test_get_cashback_categories_returns_paginated_envelope(
        self, api, admin_headers,
    ):
        """PRD §2.3: "The meta object of a list response carries the
        four pagination fields limit, offset, total_count, and
        has_more."

        Claim: GET /cashback-categories returns a paginated envelope.
        """
        resp = api.list_cashback_categories(admin_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta


# ===========================================================================
# Pagination bounds — PRD §2.3
# ===========================================================================
class TestPaginationBounds:
    """PRD §2.3 limit/offset bounds."""

    def test_limit_zero_rejected(self, api, admin_headers):
        """PRD §2.3: "limit, which bounds the page size with a default
        of 10, a minimum of 1, and a maximum of 100".

        Claim: limit=0 -> ERR_VALIDATION (below minimum of 1).
        """
        resp = api.list_cashback_categories(
            admin_headers, params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_over_max_rejected(self, api, admin_headers):
        """PRD §2.3: "limit, which bounds the page size with a default
        of 10, a minimum of 1, and a maximum of 100".

        Claim: limit=101 -> ERR_VALIDATION (above maximum of 100).
        """
        resp = api.list_cashback_categories(
            admin_headers, params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_limit_min_accepted(self, api, admin_headers):
        """PRD §2.3: "limit, which bounds the page size with a default
        of 10, a minimum of 1, and a maximum of 100".

        Claim: limit=1 (boundary) is accepted.
        """
        resp = api.list_cashback_categories(
            admin_headers, params={"limit": 1},
        )
        validate_paginated(resp)

    def test_limit_max_accepted(self, api, admin_headers):
        """PRD §2.3: "limit, which bounds the page size with a default
        of 10, a minimum of 1, and a maximum of 100".

        Claim: limit=100 (boundary) is accepted.
        """
        resp = api.list_cashback_categories(
            admin_headers, params={"limit": 100},
        )
        validate_paginated(resp)


# ===========================================================================
# Path-segment 404 — PRD §2.5
# ===========================================================================
class TestPathNotFound:
    """PRD §2.5 left-to-right path resolution."""

    def test_get_account_not_found(self, api, admin_headers):
        """PRD §2.5: "The first identifier that does not resolve produces
        ERR_NOT_FOUND immediately, before later segments or request
        bodies are examined."

        Claim: GET /accounts/{NON_EXISTENT_UUID} -> ERR_NOT_FOUND.
        """
        resp = api.get_account(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_transaction_not_found(self, api, admin_headers):
        """PRD §2.5: "The first identifier that does not resolve produces
        ERR_NOT_FOUND immediately."

        Claim: GET /transactions/{NON_EXISTENT_UUID} -> ERR_NOT_FOUND.
        """
        resp = api.get_transaction(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_cardholder_not_found(self, api, admin_headers):
        """PRD §2.5: "The first identifier that does not resolve produces
        ERR_NOT_FOUND immediately."

        Claim: GET /cardholders/{NON_EXISTENT_UUID} -> ERR_NOT_FOUND.
        """
        resp = api.get_cardholder(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Error envelope shape — PRD §2.2
# ===========================================================================
class TestErrorEnvelope:
    """PRD §2.2 error envelope shape."""

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: a 4xx response carries error_id and message in data.
        """
        resp = api._request("GET", "/cashback-categories", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""
