"""Auth, response envelope, pagination, and nested-path resolution.

Covers PRD §2.1 (auth headers + role authorisation), §2.2 (envelope
shape), §2.3 (pagination), §2.4 (UUID / ISO 8601 / version), and §2.6
(nested path left-to-right resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_advertiser_payload,
    create_campaign_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_active_advertiser,
    setup_active_campaign_with_approved_creative,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing / unknown auth headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_returns_missing_user_context(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_MISSING_USER_CONTEXT and an HTTP 401 status."

        Claim: omitting X-User-ID -> ERR_MISSING_USER_CONTEXT, 401.
        """
        headers = {"X-User-Role": "PlatformAdmin"}
        res = api.create_advertiser(create_advertiser_payload(), headers)
        validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)

    def test_missing_user_role_header_returns_missing_user_context(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_MISSING_USER_CONTEXT and an HTTP 401 status."

        Claim: omitting X-User-Role -> ERR_MISSING_USER_CONTEXT, 401.
        """
        headers = {"X-User-ID": "anyone-1"}
        res = api.create_advertiser(create_advertiser_payload(), headers)
        validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)

    def test_unknown_role_returns_forbidden_role(self, api):
        """PRD §2.1: "A request that carries both headers but whose role
        is unknown to the system, or whose role is not authorised for
        the requested operation, is rejected with ERR_FORBIDDEN_ROLE and
        an HTTP 403 status."

        Claim: unknown X-User-Role -> ERR_FORBIDDEN_ROLE, 403.
        """
        headers = build_user_headers("op-1", "Janitor")
        res = api.create_advertiser(create_advertiser_payload(), headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_role_not_authorised_for_operation_returns_forbidden_role(self, api):
        """PRD §2.1: "or whose role is not authorised for the requested
        operation, is rejected with ERR_FORBIDDEN_ROLE and an HTTP 403
        status."

        Claim: CreativeReviewer is not on the PlatformAdmin-only roster
        for POST /advertisers (PRD §4 lists PlatformAdmin only) ->
        ERR_FORBIDDEN_ROLE, 403.
        """
        res = api.create_advertiser(
            create_advertiser_payload(),
            TEST_USERS["creative_reviewer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Success envelope shape (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:

    def test_create_advertiser_returns_201_with_envelope(self, api):
        """PRD §2.2: "Creation endpoints return HTTP 201 on success."
        PRD §2.2 envelope: api_request_id starts with 'req_';
        api_request_timestamp is ISO 8601 UTC with three fractional
        digits; response_type is 'object' for a single resource.

        Claim: create-advertiser success envelope conforms.
        """
        res = api.create_advertiser(
            create_advertiser_payload(),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert is_valid_uuid(data["id"])

    def test_get_returns_200(self, api):
        """PRD §4: "non-creation mutations and reads return HTTP 200."

        Claim: GET /advertisers returns 200.
        """
        res = api.list_advertisers(TEST_USERS["platform_admin_headers"])
        assert res.status_code == 200, (
            f"PRD §4 mandates 200 for reads, got {res.status_code}"
        )


# ===========================================================================
# Error envelope shape (PRD §2.2)
# ===========================================================================
class TestErrorEnvelope:

    def test_error_envelope_has_response_type_and_error_id(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."

        Claim: error response has response_type='error' and data.error_id.
        """
        res = api.create_advertiser(create_advertiser_payload(), {})
        body = res.json()
        assert body["response_type"] == "error", (
            f"PRD §2.2: response_type must be 'error' for 4xx, got "
            f"{body.get('response_type')!r}"
        )
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_default_pagination_envelope_fields_present(self, api):
        """PRD §2.3: "When a list endpoint returns, the response meta
        includes limit, offset, total_count (the total number of rows
        matching any filter, before pagination), and has_more (true when
        more rows exist beyond the current page)."

        Claim: list response meta carries limit / offset / total_count /
        has_more.
        """
        res = api.list_advertisers(TEST_USERS["platform_admin_headers"])
        data, meta = validate_paginated(res)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 10, (
            "PRD §2.3: default limit is 10"
        )
        assert meta["offset"] == 0, (
            "PRD §2.3: default offset is 0"
        )


# ===========================================================================
# Nested-path resolution (PRD §2.6)
# ===========================================================================
class TestNestedPathResolution:

    def test_unknown_advertiser_id_returns_advertiser_not_found(self, api):
        """PRD §2.6: "If the first identifier in the path does not
        resolve, the system returns ERR_ADVERTISER_NOT_FOUND and does
        not attempt to resolve any further segment."

        Claim: GET /advertisers/{nonexistent} -> ERR_ADVERTISER_NOT_FOUND.
        """
        res = api.get_advertiser(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_NOT_FOUND.value)

    def test_unknown_campaign_under_existing_advertiser_returns_campaign_not_found(
        self, api,
    ):
        """PRD §2.6: "if the second fails, ERR_CAMPAIGN_NOT_FOUND."

        Claim: GET /advertisers/{aid}/campaigns/{nonexistent} ->
        ERR_CAMPAIGN_NOT_FOUND.
        """
        bundle = setup_active_advertiser()
        advertiser = bundle["advertiser"]
        # We don't have a direct get-campaign endpoint in the PRD, but
        # PUT requires existence and surfaces the same nested-path
        # resolution. PRD §2.6 says the same left-to-right principle
        # applies to all four ids.
        res = api.update_campaign(
            advertiser["id"], NON_EXISTENT_UUID,
            {"name": "Renamed"},
            bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value)

    def test_unknown_ad_group_under_existing_campaign_returns_ad_group_not_found(
        self, api,
    ):
        """PRD §2.6: "then ERR_AD_GROUP_NOT_FOUND."

        Claim: nested ad-group activate on unknown ad-group id ->
        ERR_AD_GROUP_NOT_FOUND.
        """
        setup = setup_active_campaign_with_approved_creative()
        res = api.activate_ad_group(
            setup["advertiser"]["id"], setup["campaign"]["id"],
            NON_EXISTENT_UUID, setup["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_AD_GROUP_NOT_FOUND.value)

    def test_unknown_creative_id_returns_creative_not_found(self, api):
        """PRD §2.6: "then ERR_CREATIVE_NOT_FOUND. All four are returned
        at HTTP 404."

        Claim: POST /creatives/{nonexistent}/archive -> ERR_CREATIVE_NOT_FOUND.
        """
        bundle = setup_active_advertiser()
        res = api.archive_creative(
            NON_EXISTENT_UUID, bundle["manager_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CREATIVE_NOT_FOUND.value)

    def test_path_resolution_short_circuits_on_first_failure(self, api):
        """PRD §2.6: "If the first identifier in the path does not
        resolve, the system returns ERR_ADVERTISER_NOT_FOUND and does
        not attempt to resolve any further segment."

        Claim: when advertiser id AND campaign id are both unknown, the
        advertiser failure pre-empts — ERR_ADVERTISER_NOT_FOUND wins
        over ERR_CAMPAIGN_NOT_FOUND.
        """
        # Build a campaign-manager header for a real-looking external id —
        # the auth path passes (role is recognized), so the test reaches
        # the path-resolution stage.
        from test_helpers import make_campaign_manager_headers
        res = api.update_campaign(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            {"name": "x"},
            make_campaign_manager_headers("anybody"),
        )
        validate_error(res, ApiErrorId.ERR_ADVERTISER_NOT_FOUND.value)
