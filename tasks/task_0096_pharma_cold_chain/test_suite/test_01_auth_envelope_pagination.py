"""Auth, response envelope, pagination, OCC, identifier conventions.

PRD §2.1 RBAC headers, §2.2 envelope, §2.3 pagination, §2.4 ids,
§2.5 optimistic concurrency, §2.6 status codes. These tests exercise
the universal request/response contract that every endpoint inherits.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_warehouse_payload,
    create_zone_payload,
    create_warehouse,
    create_zone,
    create_bin,
    create_supplier,
    create_product,
    create_supplier_payload,
    create_product_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_accepted_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing / unrecognized auth headers — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_role_header_rejected_with_err_auth_missing_role(self, api):
        """PRD §2.1: "A request missing the role header is rejected with
        `ERR_AUTH_MISSING_ROLE` (HTTP 401)".

        Claim: omitting X-User-Role yields ERR_AUTH_MISSING_ROLE / 401.
        """
        headers = {"X-User-ID": "anybody", "Content-Type": "application/json"}
        res = api.create_warehouse(create_warehouse_payload(), headers)
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING_ROLE.value)

    def test_missing_user_header_rejected_with_err_auth_missing_user(self, api):
        """PRD §2.1: "a request missing the user header is rejected
        with `ERR_AUTH_MISSING_USER` (HTTP 401)".

        Claim: omitting X-User-ID yields ERR_AUTH_MISSING_USER / 401.
        """
        headers = {"X-User-Role": "WarehouseAdmin",
                   "Content-Type": "application/json"}
        res = api.create_warehouse(create_warehouse_payload(), headers)
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING_USER.value)

    @pytest.mark.parametrize("call_name,maker", [
        ("create_supplier",
         lambda api, h: api.create_supplier(create_supplier_payload(), h)),
        ("create_product",
         lambda api, h: api.create_product(create_product_payload(), h)),
    ])
    def test_role_not_authorised_yields_err_forbidden(
        self, api, call_name, maker,
    ):
        """PRD §2.1: "a request whose role is not authorised for the
        requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Claim: a Receiver attempting WarehouseAdmin-only endpoints
        yields ERR_FORBIDDEN / 403.
        """
        res = maker(api, TEST_USERS["receiver_headers"])
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_carries_required_meta_fields(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated
        ISO 8601 UTC timestamp with three fractional digits."

        Claim: success.meta has api_request_id starting with `req_`
        and api_request_timestamp in ISO 8601 form.
        """
        res = api.create_warehouse(
            create_warehouse_payload(),
            TEST_USERS["warehouse_admin_headers"],
        )
        body = res.json()
        assert "meta" in body
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert "data" in body

    def test_create_warehouse_returns_201(self, api):
        """PRD §2.6: "A request that mints a brand-new resource returns
        HTTP 201; every other successful operation ... returns HTTP 200."

        Claim: create_warehouse returns 201 and the envelope.data is
        the created Warehouse with id, created_at, version=1.
        """
        res = api.create_warehouse(
            create_warehouse_payload(),
            TEST_USERS["warehouse_admin_headers"],
        )
        data = validate_success(res, 201)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["clock_minutes"] == 0  # PRD §3.1 default
        assert data["status"] == "ACTIVE"  # PRD §3.1 default


# ===========================================================================
# 404 on missing path-bound resources — PRD §2.4
# ===========================================================================
class TestNotFound:

    def test_get_warehouse_nonexistent_returns_err_not_found(self, api):
        """PRD §2.4: "path parameters are validated left to right: the
        outer resource is checked first, the inner second, and the
        first failure short-circuits with `ERR_NOT_FOUND`."

        Claim: GET /warehouses/{wid} on unknown wid yields
        ERR_NOT_FOUND / 404.
        """
        res = api.get_warehouse(
            NON_EXISTENT_UUID, TEST_USERS["warehouse_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_zone_nonexistent_returns_err_not_found(self, api):
        res = api.get_zone(
            NON_EXISTENT_UUID, TEST_USERS["warehouse_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_warehouses_returns_pagination_meta(self, api):
        """PRD §2.3: "List responses populate `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` block".

        Claim: list endpoints emit limit/offset/total_count/has_more
        in meta.
        """
        # Mint a couple of warehouses to ensure at least 1 in list.
        create_warehouse()
        create_warehouse()
        res = api.list_warehouses(TEST_USERS["warehouse_admin_headers"])
        data, meta = validate_paginated(res)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta
        assert isinstance(data, list)
        assert meta["total_count"] >= 2

    def test_list_warehouses_default_limit_is_10(self, api):
        """PRD §2.3: "`limit` defaults to 10".

        Claim: omitting limit returns meta.limit==10.
        """
        # No need to create 10 — we only check meta.limit.
        res = api.list_warehouses(TEST_USERS["warehouse_admin_headers"])
        _, meta = validate_paginated(res)
        assert meta["limit"] == 10


# ===========================================================================
# Optimistic concurrency control — PRD §2.5
# ===========================================================================
class TestOptimisticConcurrency:

    def test_version_mismatch_returns_err_version_conflict(self, api):
        """PRD §2.5: "When `version` is supplied, the server compares
        it against the resource's current `version`; a mismatch is
        rejected with `ERR_VERSION_CONFLICT` (HTTP 409)."

        Claim: supplying a stale version on a state-changing endpoint
        yields ERR_VERSION_CONFLICT / 409.
        """
        ctx = setup_accepted_lot(quantity_units=1)
        # The accepted receipt is at some version >= 1. Try cancel-
        # equivalent via an action endpoint passing a wrong version.
        # We use the receipt reject endpoint — but receipt is already
        # ACCEPTED so the state check would short-circuit. Better to
        # exercise OCC against a freshly-created INSPECTED receipt
        # whose state allows accept.
        from test_helpers import (
            create_inspected_receipt,
            setup_basic_topology,
            setup_qualified_supplier_and_product,
        )
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        # The receipt version is whatever inspect minted; submit
        # accept with version=999 (very stale).
        res = api.accept_receipt(
            receipt["id"],
            TEST_USERS["qa_officer_headers"],
            payload={"version": 999},
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_version_increments_on_mutation(self, api):
        """PRD §2.5: "On every successful mutation the affected
        resource's `version` increments by exactly 1 and its
        `updated_at` refreshes."

        Claim: inspect transitions PENDING_INSPECTION → INSPECTED and
        bumps version by exactly 1.
        """
        from test_helpers import (
            create_pending_receipt,
            inspect_receipt,
            setup_basic_topology,
            setup_qualified_supplier_and_product,
        )
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        pending = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        v0 = pending["version"]
        inspected = inspect_receipt(pending["id"])
        assert inspected["version"] == v0 + 1, (
            f"version did not increment by exactly 1: {v0} -> "
            f"{inspected['version']}"
        )
        assert inspected["updated_at"] != pending["updated_at"]
