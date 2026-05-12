"""Auth, RBAC, envelope, pagination, and path-existence checks.

PRD references:
  - §2.1 Authentication and RBAC
  - §2.2 API Response Structure
  - §2.3 Pagination
  - §2.7 Nested-Resource Path Validation
  - §2.8 Validation Priority
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    create_recipe_payload,
    create_store_payload,
    create_vehicle_payload,
    validate_error,
    validate_paginated,
    validate_success,
    create_store,
    setup_store_with_recipe,
    setup_submitted_order,
)


# ===========================================================================
# §2.1 — Auth header presence
# ===========================================================================
class TestAuthHeaders:
    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-ID → ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api.create_store(create_store_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'When either header is missing the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: missing X-User-Role → ERR_AUTH_REQUIRED.
        """
        bad = {"X-User-ID": "admin-001"}
        res = api.create_store(create_store_payload(), bad)
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_both_headers_missing_rejected(self, api):
        """PRD §2.1: 'When either header is missing the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401).'

        Claim: no auth headers at all → ERR_AUTH_REQUIRED.
        """
        res = api.create_store(create_store_payload(), {})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unknown_role_value_rejected(self, api):
        """PRD §2.1: 'When X-User-Role does not name one of the five roles
        defined below, the request is rejected with ERR_INVALID_ROLE
        (HTTP 401).'

        Claim: bogus role string → ERR_INVALID_ROLE.
        """
        headers = build_user_headers("anyone", "GalacticOverlord")
        res = api.create_store(create_store_payload(), headers)
        validate_error(res, "ERR_INVALID_ROLE")


# ===========================================================================
# §2.1 — RBAC
# ===========================================================================
class TestRBAC:
    @pytest.mark.parametrize(
        "role",
        ["CentralKitchenPlanner", "StoreManager", "Driver",
         "FinanceController"],
    )
    def test_create_store_requires_platform_admin(self, api, role):
        """PRD §2.1: 'When the role is recognized but is not authorized to
        invoke the targeted endpoint, the request is rejected with
        ERR_FORBIDDEN (HTTP 403).'
        PRD §4: 'POST /supply-chain/stores ... Authorized Role(s): PlatformAdmin'.

        Claim: non-PlatformAdmin role hitting POST /stores → ERR_FORBIDDEN.
        """
        headers = build_user_headers(f"some-{role}", role)
        res = api.create_store(create_store_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    @pytest.mark.parametrize(
        "role",
        ["PlatformAdmin", "StoreManager", "Driver", "FinanceController"],
    )
    def test_create_recipe_requires_planner(self, api, role):
        """PRD §4: 'POST /supply-chain/recipes ... Authorized Role(s):
        CentralKitchenPlanner'.
        PRD §2.1: 'When the role is recognized but is not authorized to
        invoke the targeted endpoint, the request is rejected with
        ERR_FORBIDDEN (HTTP 403).'

        Claim: non-CentralKitchenPlanner roles → ERR_FORBIDDEN on create_recipe.
        """
        headers = build_user_headers(f"some-{role}", role)
        res = api.create_recipe(create_recipe_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_create_vehicle_requires_platform_admin(
        self, api, planner_headers
    ):
        """PRD §4: 'POST /supply-chain/vehicles ... Authorized Role(s):
        PlatformAdmin'.

        Claim: a CentralKitchenPlanner creating a vehicle → ERR_FORBIDDEN.
        """
        res = api.create_vehicle(create_vehicle_payload(), planner_headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_run_cost_allocation_requires_finance(self, api, planner_headers):
        """PRD §4: 'POST /supply-chain/cost-allocations/run ... Authorized
        Role(s): FinanceController'.

        Claim: a CentralKitchenPlanner running cost allocation → ERR_FORBIDDEN.
        """
        res = api.run_cost_allocation(
            {
                "period_start": "2026-05-01T00:00:00.000Z",
                "period_end": "2026-05-02T00:00:00.000Z",
                "indirect_basis": "SALES_VALUE",
            },
            planner_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_advance_clock_requires_platform_admin(self, api, finance_headers):
        """PRD §2.11: 'A clock-advance capability ... All four are restricted
        to PlatformAdmin.'

        Claim: non-PlatformAdmin calling /_clock/advance → ERR_FORBIDDEN.
        """
        res = api.advance_clock(
            "2026-05-11T00:00:00.000Z", finance_headers
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.7 — Path existence (left-to-right)
# ===========================================================================
class TestPathExistence:
    def test_get_unknown_store_returns_not_found(
        self, api, platform_admin_headers
    ):
        """PRD §2.7: 'The leftmost path-referenced resource is checked first;
        if it does not exist, the request is rejected with ERR_NOT_FOUND
        (HTTP 404) before any further checks fire.'

        Claim: GET /stores/{unknown-uuid} → ERR_NOT_FOUND.
        """
        res = api.get_store(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_schedule_unknown_batch_returns_not_found(
        self, api, planner_headers
    ):
        """PRD §2.7: leftmost path resource missing → ERR_NOT_FOUND.

        Claim: POST /production-batches/{unknown}/schedule → ERR_NOT_FOUND.
        """
        res = api.schedule_production_batch(
            NON_EXISTENT_UUID, planner_headers
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 — Success envelope shape
# ===========================================================================
class TestSuccessEnvelope:
    def test_create_store_returns_envelope_and_201(self, api):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with response_type 'object' and a data resource field.
        PRD §4 row: 'POST /supply-chain/stores ... 201'.

        Claim: POST /stores returns 201 + standard success envelope.
        """
        from test_helpers import TEST_USERS
        res = api.create_store(
            create_store_payload(),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict)
        assert "id" in data


# ===========================================================================
# §2.3 — Pagination
# ===========================================================================
class TestPagination:
    def test_list_stores_returns_pagination_meta(
        self, api, platform_admin_headers
    ):
        """PRD §2.3: 'The meta object on a list response includes limit,
        offset, total_count (the total number of records matching the
        filter), and has_more (true when offset + limit < total_count).'

        Claim: GET /stores returns paginated envelope with the four meta keys.
        """
        # Ensure at least one store exists.
        create_store()
        res = api.list_stores(platform_admin_headers)
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta

    def test_list_stores_default_limit_is_10(
        self, api, platform_admin_headers
    ):
        """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
        maximum is 100; values outside this band are rejected.'

        Claim: GET /stores with no limit returns meta.limit == 10.
        """
        res = api.list_stores(platform_admin_headers)
        _, meta = validate_paginated(res)
        assert meta["limit"] == 10
