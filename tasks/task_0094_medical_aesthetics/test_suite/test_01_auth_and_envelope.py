"""Auth, response envelope, and pagination — PRD §2.1, §2.2, §2.3.

These tests exercise the universal request/response contract that all
endpoints inherit. They are intentionally small so failures here
isolate one envelope concern at a time.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_consumable_sku,
    create_consumable_sku_payload,
    create_customer,
    create_customer_payload,
    create_kyc_verified_customer,
    create_on_shelf_project,
    create_room_payload,
    is_iso8601_timestamp,
    list_audit_entries,
    list_projects,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing or unrecognized auth headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a
        X-User-Role value the system does not recognize, is rejected
        with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: missing X-User-ID → ERR_UNAUTHENTICATED, 401.
        """
        headers = {"X-User-Role": "MedicalDirector"}
        res = api.create_consumable_sku(
            create_consumable_sku_payload(), headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a
        X-User-Role value the system does not recognize, is rejected
        with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: missing X-User-Role → ERR_UNAUTHENTICATED, 401.
        """
        headers = {"X-User-ID": "anybody"}
        res = api.create_consumable_sku(
            create_consumable_sku_payload(), headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a
        X-User-Role value the system does not recognize, is rejected
        with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: unrecognized X-User-Role → ERR_UNAUTHENTICATED, 401.
        """
        headers = build_user_headers("anybody", "Janitor")
        res = api.create_consumable_sku(
            create_consumable_sku_payload(), headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_role_not_permitted_for_endpoint(self, api):
        """PRD §2.1: "A request with both headers present but whose role
        is not permitted to invoke the target endpoint per the RBAC
        matrix in §4 is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Consultant cannot register a SKU (MedicalDirector only).
        """
        res = api.create_consumable_sku(
            create_consumable_sku_payload(),
            TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope shape (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_has_required_meta_fields(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: success response.meta.api_request_id begins with 'req_'
        and api_request_timestamp is ISO 8601.
        """
        res = api.create_consumable_sku(
            create_consumable_sku_payload(),
            TEST_USERS["medical_director_headers"],
        )
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert "data" in body

    def test_create_returns_201_and_resource(self, api):
        """PRD §4: "New-resource creation endpoints return HTTP 201."

        Claim: POST /aesthetics/consumable-skus returns 201 plus the
        created resource in response.data.
        """
        res = api.create_consumable_sku(
            create_consumable_sku_payload(),
            TEST_USERS["medical_director_headers"],
        )
        data = validate_success(res, 201)
        assert isinstance(data["id"], str) and len(data["id"]) > 0


# ===========================================================================
# Pagination contract (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_list_envelope_has_pagination_meta(self, api):
        """PRD §2.3: "The fields limit, offset, total_count, and
        has_more are included in the meta envelope of every list
        response."

        Claim: list response.meta carries limit/offset/total_count/has_more.
        """
        # Seed at least one row so list returns it.
        create_on_shelf_project()
        rows, meta = validate_paginated(
            api.list_projects(TEST_USERS["medical_director_headers"])
        )
        assert isinstance(rows, list)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta.{key} missing"
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_pagination_default_limit_is_ten(self, api):
        """PRD §2.3: "The limit defaults to 10, has a minimum of 1, and
        a maximum of 100; offset defaults to 0."

        Claim: omitted limit yields meta.limit == 10.
        """
        create_on_shelf_project()
        _, meta = validate_paginated(
            api.list_projects(TEST_USERS["medical_director_headers"])
        )
        assert meta["limit"] == 10

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 500])
    def test_limit_out_of_range_rejected(self, api, bad_limit):
        """PRD §2.3: "Any request that supplies a limit outside the
        1-to-100 range, or an offset below 0, is rejected with
        ERR_PAGINATION_OUT_OF_RANGE (HTTP 400)."

        Claim: limit outside [1, 100] → ERR_PAGINATION_OUT_OF_RANGE, 400.
        """
        res = api.list_projects(
            TEST_USERS["medical_director_headers"],
            params={"limit": bad_limit},
        )
        validate_error(res, ApiErrorId.ERR_PAGINATION_OUT_OF_RANGE.value)

    @pytest.mark.parametrize("bad_offset", [-1, -10])
    def test_offset_below_zero_rejected(self, api, bad_offset):
        """PRD §2.3: "Any request that supplies a limit outside the
        1-to-100 range, or an offset below 0, is rejected with
        ERR_PAGINATION_OUT_OF_RANGE (HTTP 400)."

        Claim: offset below 0 → ERR_PAGINATION_OUT_OF_RANGE, 400.
        """
        res = api.list_projects(
            TEST_USERS["medical_director_headers"],
            params={"offset": bad_offset},
        )
        validate_error(res, ApiErrorId.ERR_PAGINATION_OUT_OF_RANGE.value)

    def test_limit_boundary_values_accepted(self, api):
        """PRD §2.3: "The limit defaults to 10, has a minimum of 1, and
        a maximum of 100; offset defaults to 0."

        Claim: limit=1 and limit=100 succeed (inclusive boundaries).
        """
        create_on_shelf_project()
        for ok_limit in (1, 100):
            _, meta = validate_paginated(
                api.list_projects(
                    TEST_USERS["medical_director_headers"],
                    params={"limit": ok_limit},
                )
            )
            assert meta["limit"] == ok_limit


# ===========================================================================
# NotFound on path-bearing endpoints (PRD §2.5)
# ===========================================================================
class TestNotFound:

    def test_get_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "the first one that does not exist or fails an
        ownership check causes the request to be rejected with
        ERR_NOT_FOUND (HTTP 404)."

        Claim: GET /aesthetics/customers/{unknown} → ERR_NOT_FOUND, 404.
        """
        res = api.get_customer(
            NON_EXISTENT_UUID, TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Schema / required-field validation (PRD §2.5, §2.6)
# ===========================================================================
class TestSchemaValidation:

    @pytest.mark.parametrize(
        "missing_field",
        ["sku_code", "name", "kind"],
    )
    def test_missing_required_sku_field_rejected(self, api, missing_field):
        """PRD §2.5: "Schema/type validation of the request body
        (required keys present, types correct) precedes business
        rules; a malformed body yields ERR_INVALID_INPUT (HTTP 400)."

        Claim: omitting a required SKU input field → ERR_INVALID_INPUT, 400.
        """
        payload = create_consumable_sku_payload()
        del payload[missing_field]
        res = api.create_consumable_sku(
            payload, TEST_USERS["medical_director_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.5: "Schema/type validation of the request body
        (required keys present, types correct) precedes business
        rules; a malformed body yields ERR_INVALID_INPUT (HTTP 400)."

        Claim: invalid `kind` enum value on SKU → ERR_INVALID_INPUT, 400.
        """
        payload = create_consumable_sku_payload(kind="ROBOT")
        res = api.create_consumable_sku(
            payload, TEST_USERS["medical_director_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)
