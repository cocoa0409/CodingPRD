"""Deal creation defaults, creation-date constraints, and the read surface."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_deal,
    assert_ts_prefix,
    create_deal,
    create_deal_payload,
    create_property_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDealCreationDefaults:
    def test_deal_creation_applies_defaults_and_system_fields(self, api,
                                                              analyst_headers):
        """PRD §3.1: "The `sourcing_channel` — one of `BROKER`, `OFF_MARKET`,
        `AUCTION`, or `DIRECT` — defaults to `BROKER` when omitted."
        PRD §3.1: "A new deal is born with `status` `SOURCING`, `posture`
        `SOURCING`, and `earnest_money_released` false."
        PRD §2.4: "Every entity in the system carries a server-minted `id`
        formatted as a bare UUID with no type prefix, plus a `created_at`
        timestamp in ISO 8601 UTC with three fractional digits."

        Design: Corner/entities/deal_creation_applies_defaults_and_system_fields
        """
        payload = create_deal_payload(deal_name="DefaultsDeal")
        assert "sourcing_channel" not in payload
        deal = validate_success(api.create_deal(payload, analyst_headers), 201)
        assert_deal(deal)
        assert deal["sourcing_channel"] == "BROKER", (
            "sourcing_channel defaults to BROKER when omitted")
        assert deal["status"] == "SOURCING"
        assert deal["posture"] == "SOURCING"
        assert deal["earnest_money_released"] is False
        assert is_valid_uuid(deal["id"]), "id is a bare UUID with no prefix"
        assert is_iso8601_timestamp(deal["created_at"])
        assert is_iso8601_timestamp(deal["updated_at"])
        assert isinstance(deal["version"], int), "version is an integer"

        fetched = validate_success(api.get_deal(deal["id"], analyst_headers))
        assert fetched["sourcing_channel"] == "BROKER"
        assert fetched["status"] == "SOURCING"

    def test_deal_target_close_date_below_30_days_rejected(self, api,
                                                           analyst_headers):
        """PRD §3.1: "The target close date must fall at least 30 days after
        the deal's creation date; anything closer is rejected with
        `ERR_FIELD_CONSTRAINT_VIOLATION` (HTTP 400)."
        PRD §2.6: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z`"

        Design: Corner/entities/deal_target_close_date_below_30_days_rejected
        """
        # 20 days after the 2026-08-01 startup clock: too close.
        too_soon = api.create_deal(
            create_deal_payload(deal_name="TooSoon",
                                target_close_date="2026-08-21T00:00:00Z"),
            analyst_headers)
        validate_error(too_soon, ApiErrorId.ERR_FIELD_CONSTRAINT_VIOLATION)

        # Exactly 30 days after creation: the floor is inclusive.
        exactly_30 = api.create_deal(
            create_deal_payload(deal_name="ExactlyThirty",
                                target_close_date="2026-08-31T00:00:00Z"),
            analyst_headers)
        deal = validate_success(exactly_30, 201)
        assert_ts_prefix(deal["target_close_date"], "2026-08-31T00:00:00")


class TestDealReadSurface:
    def test_deal_get_not_found_returns_404(self, api, analyst_headers):
        """PRD §2.8: "A request naming a deal, then a property, then a lease
        first checks the deal's existence (else `ERR_DEAL_NOT_FOUND`)"
        PRD §5: "`ERR_DEAL_NOT_FOUND` | 404"

        Design: Corner/entities/deal_get_not_found_returns_404
        """
        resp = api.get_deal(NON_EXISTENT_UUID, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_FOUND)

    def test_deal_list_pagination_envelope(self, api, analyst_headers):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults
        to 10, with a minimum of 1 and a maximum of 100. `offset` skips that
        many items from the front of the result set and defaults to 0."
        PRD §2.3: "The `meta` envelope of a list response carries `limit`,
        `offset`, `total_count`, and `has_more` so a client can page
        deterministically through a collection."

        Design: Corner/entities/deal_list_pagination_envelope
        """
        for name in ("D1", "D2", "D3"):
            create_deal(deal_name=name)
        resp = api.list_deals(analyst_headers, params={"limit": 2,
                                                       "offset": 0})
        assert resp.json()["response_type"] == "array", (
            "A list of resources carries response_type array")
        data, meta = validate_paginated(resp)
        assert len(data) == 2, "limit=2 caps the page at two deals"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert isinstance(meta["api_request_id"], str)

    def test_property_parent_relationship_wrong_deal_returns_404(
            self, api, analyst_headers):
        """PRD §2.8: "A request naming a deal, then a property, then a lease
        first checks the deal's existence (else `ERR_DEAL_NOT_FOUND`), then
        the property within that deal (else `ERR_PROPERTY_NOT_FOUND`)"

        Design: Corner/entities/property_parent_relationship_wrong_deal_returns_404
        """
        deal_a = create_deal(deal_name="ParentA")
        deal_b = create_deal(deal_name="ParentB")
        prop_b = get_success_data(api.create_property(
            deal_b["id"], create_property_payload(address="1 B St"),
            analyst_headers))
        resp = api.get_property(deal_a["id"], prop_b["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
