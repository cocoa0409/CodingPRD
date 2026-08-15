"""Asset registration, response envelope, pagination, and authentication."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_asset,
    create_asset_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

DM = TEST_USERS["dm_headers"]


class TestAssetCreation:
    def test_create_asset_returns_201_with_system_defaults(self, api):
        """PRD: "Operations that create a new, stand-alone resource — an asset,
        analysis, engagement, package, bidder, bid, purchase agreement,
        due-diligence item, payoff quote, or closing statement — return `201
        Created`"
        PRD: "The new asset starts life with `marketing_status` at `EVALUATION`,
        `deal_status` at `IDLE`, `forfeited_deposits_cents` at 0, and
        `offers_deadline`, `last_campaign_closed_at`, and
        `final_sale_price_cents` all null."

        Design: Corner/entities/create_asset_returns_201_with_system_defaults
        """
        resp = api.create_asset(create_asset_payload(), DM)
        asset = validate_success(resp, 201)
        assert_asset(asset)
        assert asset["marketing_status"] == "EVALUATION"
        assert asset["deal_status"] == "IDLE"
        assert asset["forfeited_deposits_cents"] == 0
        assert asset["offers_deadline"] is None
        assert asset["last_campaign_closed_at"] is None
        assert asset["final_sale_price_cents"] is None
        assert is_valid_uuid(asset["id"])
        assert is_iso8601_timestamp(asset["created_at"])
        assert is_iso8601_timestamp(asset["updated_at"])

    def test_create_asset_invalid_enum_returns_invalid_request(self, api):
        """PRD: "Request shape comes fourth: missing required fields, invalid
        enum values, violated integer ranges, a `window_end` that is not after
        its `window_start`, or an amount that must be positive but is not, all
        yield `ERR_INVALID_REQUEST`."
        PRD: "its `asset_type` — one of `OFFICE`, `INDUSTRIAL`, `RETAIL`, or
        `MULTIFAMILY`"

        Design: Corner/entities/create_asset_invalid_enum_returns_invalid_request
        """
        payload = create_asset_payload(asset_type="WAREHOUSE")
        resp = api.create_asset(payload, DM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_asset_missing_name_returns_invalid_request(self, api):
        """PRD: "Request shape comes fourth: missing required fields, invalid
        enum values, violated integer ranges, a `window_end` that is not after
        its `window_start`, or an amount that must be positive but is not, all
        yield `ERR_INVALID_REQUEST`."
        PRD: "Registration captures the property's `name` and `market`"

        Design: Corner/entities/create_asset_missing_name_returns_invalid_request
        """
        payload = create_asset_payload()
        del payload["name"]
        resp = api.create_asset(payload, DM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAssetReads:
    def test_get_asset_not_found_returns_404(self, api):
        """PRD: "Existence comes third: any identifier in the path or request
        body that does not resolve to an existing resource yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_asset_not_found_returns_404
        """
        resp = api.get_asset(NON_EXISTENT_UUID, DM)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["message"].strip(), "error message must be non-empty"

    def test_list_assets_filter_and_pagination(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return."
        PRD: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD: "The asset list endpoint additionally accepts two optional filters,
        `marketing_status` and `deal_status`, which narrow the returned assets
        to the named dimension values."

        Design: Corner/entities/list_assets_filter_and_pagination
        """
        api.create_asset(create_asset_payload(name="A1", market="Dallas"), DM)
        api.create_asset(
            create_asset_payload(name="A2", market="Phoenix",
                                 asset_type="INDUSTRIAL", noi_cents=120_000_000,
                                 guidance_price_cents=1_800_000_000), DM)

        page1, meta1 = validate_paginated(
            api.list_assets(DM, params={"marketing_status": "EVALUATION",
                                        "limit": 1, "offset": 0}))
        assert len(page1) == 1, "limit must be honored"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert page1[0]["marketing_status"] == "EVALUATION"

        page2, meta2 = validate_paginated(
            api.list_assets(DM, params={"marketing_status": "EVALUATION",
                                        "limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1
        assert page2[0]["id"] != page1[0]["id"], \
            "offset page must return the other asset"


class TestEnvelopeAndAuth:
    def test_response_envelope_success_shape(self, api):
        """PRD: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
        timestamp with three fractional digits."
        PRD: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_asset(create_asset_payload(), DM)
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"]["id"], str)

    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD: "A request whose headers are missing, or whose role value is not
        one of these declared names, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD: "Authentication comes first: missing or invalid identity headers
        yield `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        # Deliberately a nonexistent id: the auth stage must fire before any
        # existence check could.
        resp = api.get_asset(NON_EXISTENT_UUID, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
