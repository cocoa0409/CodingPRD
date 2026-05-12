"""PRD §2.1 / §2.2 / §2.3 / §2.4 / §2.9 / §5: response envelope, auth
headers, role permissions, common-fields contract, pagination, NOT_FOUND
on missing path resources.

Every test cites the verbatim PRD sentence whose rule it asserts.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_payload,
    assert_clock,
    assert_fund,
    assert_investor,
    build_user_headers,
    create_fund_payload,
    create_investor_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# =====================================================================
# §2.1 Auth headers
# =====================================================================
class TestAuthHeaders:
    def test_missing_x_user_id_rejected(self, api):
        """PRD §2.1: "When either header is missing or empty, the request
        is rejected with `ERR_AUTH_HEADERS_MISSING` (HTTP 401)."

        Claim: dropping X-User-ID alone produces ERR_AUTH_HEADERS_MISSING.
        """
        headers = {"X-User-Role": "PlatformAdmin"}
        res = api.create_investor(create_investor_payload(), headers)
        validate_error(res, "ERR_AUTH_HEADERS_MISSING")

    def test_missing_x_user_role_rejected(self, api):
        """PRD §2.1: "When either header is missing or empty, the request
        is rejected with `ERR_AUTH_HEADERS_MISSING` (HTTP 401)."

        Claim: dropping X-User-Role alone produces ERR_AUTH_HEADERS_MISSING.
        """
        headers = {"X-User-ID": "anyone"}
        res = api.create_investor(create_investor_payload(), headers)
        validate_error(res, "ERR_AUTH_HEADERS_MISSING")

    def test_empty_x_user_id_rejected(self, api):
        """PRD §2.1: "When either header is missing or empty, the request
        is rejected with `ERR_AUTH_HEADERS_MISSING` (HTTP 401)."

        Claim: an empty X-User-ID is treated identically to missing.
        """
        headers = {"X-User-ID": "", "X-User-Role": "PlatformAdmin"}
        res = api.create_investor(create_investor_payload(), headers)
        validate_error(res, "ERR_AUTH_HEADERS_MISSING")

    def test_empty_x_user_role_rejected(self, api):
        """PRD §2.1: "When either header is missing or empty, the request
        is rejected with `ERR_AUTH_HEADERS_MISSING` (HTTP 401)."

        Claim: an empty X-User-Role is treated identically to missing.
        """
        headers = {"X-User-ID": "platform-admin-001", "X-User-Role": ""}
        res = api.create_investor(create_investor_payload(), headers)
        validate_error(res, "ERR_AUTH_HEADERS_MISSING")


# =====================================================================
# §2.1 RBAC -- wrong role rejected with ERR_FORBIDDEN
# =====================================================================
class TestRbacForbidden:
    def test_investor_cannot_create_fund(self, api):
        """PRD §2.1: "When both headers are present but the role is not
        authorized for the targeted endpoint per the RBAC matrix in §4,
        the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: per §4, POST /funds is exclusive to ProductOperator;
        an Investor caller is rejected with ERR_FORBIDDEN.
        """
        headers = build_user_headers("any-investor", "Investor")
        res = api.create_fund(create_fund_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_product_operator_cannot_create_investor(self, api):
        """PRD §2.1: "When both headers are present but the role is not
        authorized for the targeted endpoint per the RBAC matrix in §4,
        the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: per §4, POST /investors is PlatformAdmin-only;
        a ProductOperator is rejected.
        """
        res = api.create_investor(
            create_investor_payload(),
            TEST_USERS["product_operator_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_compliance_reviewer_cannot_advance_clock(self, api):
        """PRD §2.1: "When both headers are present but the role is not
        authorized for the targeted endpoint per the RBAC matrix in §4,
        the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Claim: per §4, POST /_clock/advance is PlatformAdmin-only;
        a ComplianceReviewer is rejected.
        """
        res = api.advance_clock(
            advance_clock_payload("2030-01-01T00:00:00.000Z"),
            TEST_USERS["compliance_reviewer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# =====================================================================
# §2.4 Common-fields contract on a freshly created entity
# =====================================================================
class TestCommonFields:
    def test_investor_carries_common_fields(self, api):
        """PRD §2.4: "Every entity carrying common fields ... exposes four
        system-managed properties on every response payload: `id`,
        `created_at`, `updated_at`, and `version`."

        Claim: a freshly created Investor exposes all four common fields,
        version starts at 1, and ids are server-minted UUIDs.
        """
        res = api.create_investor(
            create_investor_payload(legal_name="Common Fields Test"),
            TEST_USERS["platform_admin_headers"],
        )
        investor = validate_success(res, expected_status=201)
        assert_investor(investor)
        assert investor["version"] == 1, (
            "PRD §2.4: 'The `version` field is a non-negative integer that "
            "begins at 1 on creation'."
        )
        assert investor["created_at"] == investor["updated_at"], (
            "PRD §2.4: 'created_at is set once at insertion and never changes' "
            "-- on the very first response, updated_at == created_at."
        )

    def test_fund_carries_common_fields(self, api):
        """PRD §2.4: "Every entity carrying common fields (specifically
        `Investor`, `Fund`, `Order`, `Holding`, `DividendPlan`, and
        `ReconciliationRun`) exposes four system-managed properties on
        every response payload: `id`, `created_at`, `updated_at`, and
        `version`."

        Claim: a freshly created Fund exposes all four common fields.
        """
        res = api.create_fund(
            create_fund_payload(),
            TEST_USERS["product_operator_headers"],
        )
        fund = validate_success(res, expected_status=201)
        assert_fund(fund)
        assert fund["version"] == 1


# =====================================================================
# §2.3 Pagination
# =====================================================================
class TestPagination:
    def test_default_limit_and_offset(self, api):
        """PRD §2.3: "The default `limit` is 10, its minimum is 1, and its
        maximum is 100. The default `offset` is 0."

        Claim: list responses include the four pagination fields and the
        defaults are observable when no query params are supplied.
        """
        # Seed a few funds (under PlatformAdmin doing GET, ProductOperator
        # doing POST).
        for _ in range(3):
            api.create_fund(
                create_fund_payload(),
                TEST_USERS["product_operator_headers"],
            )
        res = api.list_funds(TEST_USERS["platform_admin_headers"])
        data, meta = validate_paginated(res)
        # PRD §2.3: defaults apply when client supplies neither limit nor offset
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_custom_limit_and_offset(self, api):
        """PRD §2.3: "List endpoints accept two optional query parameters:
        `limit` and `offset`."

        Claim: explicit limit/offset are honored and reflected in meta.
        """
        for _ in range(5):
            api.create_fund(
                create_fund_payload(),
                TEST_USERS["product_operator_headers"],
            )
        res = api.list_funds(
            TEST_USERS["platform_admin_headers"], params={"limit": 2}
        )
        data, meta = validate_paginated(res)
        assert meta["limit"] == 2
        assert len(data) <= 2

    def test_offset_past_end_returns_empty(self, api):
        """PRD §2.3: "`has_more` is true when `offset + limit < total_count`."

        Claim: with offset >= total_count, has_more is false and data
        is empty.
        """
        res = api.list_funds(
            TEST_USERS["platform_admin_headers"],
            params={"offset": 999_999, "limit": 10},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 0
        assert meta["has_more"] is False


# =====================================================================
# §2.9 Path resource existence
# =====================================================================
class TestPathResourceExistence:
    def test_get_nonexistent_investor_returns_not_found(self, api):
        """PRD §2.9: "the server first verifies the outermost path segment
        exists, then the next, and so on, returning `ERR_NOT_FOUND` (HTTP
        404) for the first missing segment encountered."

        Claim: GET /investors/{nonexistent_id} -> ERR_NOT_FOUND (404).
        """
        res = api.get_investor(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"]
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_fund_returns_not_found(self, api):
        """PRD §2.9: "the server first verifies the outermost path segment
        exists, then the next, and so on, returning `ERR_NOT_FOUND` (HTTP
        404) for the first missing segment encountered."

        Claim: GET /funds/{nonexistent_id} -> ERR_NOT_FOUND (404).
        """
        res = api.get_fund(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"]
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_nav_read_left_to_right_outermost_missing(self, api):
        """PRD §2.9: "the fund must exist before its NAV snapshot is looked
        up". This test asserts the outermost segment (fund_id) is the
        first missing piece detected.

        Claim: GET /funds/{nonexistent}/nav/{any-date} -> ERR_NOT_FOUND.
        """
        res = api.get_nav(
            NON_EXISTENT_UUID,
            "2026-05-04",
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
