"""Grower/grove/pool/channel entity creation rules, not-found handling,
uniqueness constraints, and the response envelope (success + pagination)."""
from test_helpers import (
    DEFAULT_CLOCK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_channel,
    assert_grove,
    assert_grower,
    create_channel_payload,
    create_grove_payload,
    create_grower_payload,
    create_pool_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestGrowerCreation:
    def test_grower_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "The new grower's `status` begins as `ACTIVE`, and two
        computed ledgers begin at zero". PRD §2.4: "Every resource in this API
        carries a uniform set of system-managed properties: an `id` that is a
        server-minted UUID with no type prefix; a `created_at` timestamp
        recording creation; an `updated_at` timestamp refreshed on every
        modification; and a `version` integer that increments with every
        mutation of the resource." PRD §2.5: "Before any client call has been
        made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it
        never falls back to wall-clock time."

        Design: Corner/entities/grower_create_applies_defaults_and_system_fields
        """
        set_clock(DEFAULT_CLOCK)
        data = validate_success(api_client.create_grower(
            create_grower_payload("GR-E1", "Entity Groves"), ADMIN),
            expected_status=201)
        assert_grower(data)
        assert data["status"] == "ACTIVE"
        assert data["advance_outstanding_cents"] == 0
        assert data["caretaking_balance_cents"] == 0
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00.000Z"
        # A subsequent read returns the same field values.
        reread = validate_success(api_client.get_grower(data["id"], ADMIN))
        assert reread == data or all(reread[k] == data[k] for k in data)

    def test_grower_create_duplicate_code_rejected(self, api):
        """PRD §3.1: "A `PackinghouseAdmin` onboards a grower by supplying a
        `grower_code` — a human-readable code that must be unique across all
        growers". PRD §2.6 tier 9: "human-readable codes and the pool's
        variety-week pair are unique (`ERR_DUPLICATE_ENTITY`)".

        Design: Corner/entities/grower_create_duplicate_code_rejected
        """
        validate_success(api_client.create_grower(
            create_grower_payload("GR-E2", "First"), ADMIN), expected_status=201)
        resp = api_client.create_grower(create_grower_payload("GR-E2", "Second"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTITY)

    def test_grower_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.6 tier 5: "required fields are present, types are valid,
        enum members are valid, and numeric ranges are respected; otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)". PRD §3.1 lists both `grower_code`
        and `display_name` as the onboarding inputs.

        Design: Corner/entities/grower_create_missing_required_returns_invalid_request
        """
        set_clock(DEFAULT_CLOCK)
        resp = api_client.create_grower({"grower_code": "GR-E3"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _rows, meta = validate_paginated(api_client.list_growers(ADMIN))
        assert meta["total_count"] == 0, "rejected create must not persist a grower"


class TestGroveCreation:
    def test_grove_get_not_found_returns_404(self, api):
        """PRD §2.6 tier 4: "every resource referenced in the path exists,
        validated left to right (§2.11); otherwise `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/entities/grove_get_not_found_returns_404
        """
        set_clock(DEFAULT_CLOCK)
        resp = api_client.get_grove(NON_EXISTENT_UUID, ADMIN)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["message"].strip(), "error message must be non-empty"

    def test_grove_invalid_variety_rejected(self, api):
        """PRD §3.1: a grove takes "a `variety` of `HAMLIN`, `VALENCIA`,
        `RED_GRAPEFRUIT`, or `TANGERINE`". PRD §2.6 tier 5: "required fields
        are present, types are valid, enum members are valid, and numeric
        ranges are respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/grove_invalid_variety_rejected
        """
        grower = validate_success(api_client.create_grower(
            create_grower_payload("GR-E5", "Enum Groves"), ADMIN), expected_status=201)
        resp = api_client.create_grove(
            create_grove_payload(grower["id"], "B1", "NAVEL", 50, "POLK"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_grove_block_code_unique_per_grower_only(self, api):
        """PRD §3.1: registration takes "a `block_code` that must be unique
        within that grower's groves". PRD §2.6 tier 9: "human-readable codes
        and the pool's variety-week pair are unique (`ERR_DUPLICATE_ENTITY`)".

        Design: Corner/entities/grove_block_code_unique_per_grower_only
        """
        grower_a = validate_success(api_client.create_grower(
            create_grower_payload("GR-E6A", "A"), ADMIN), expected_status=201)
        grower_b = validate_success(api_client.create_grower(
            create_grower_payload("GR-E6B", "B"), ADMIN), expected_status=201)
        validate_success(api_client.create_grove(
            create_grove_payload(grower_a["id"], "B1", "HAMLIN", 50, "POLK"), ADMIN),
            expected_status=201)
        # Same grower + same block_code -> conflict.
        resp = api_client.create_grove(
            create_grove_payload(grower_a["id"], "B1", "VALENCIA", 20, "POLK"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTITY)
        # Different grower + same block_code -> allowed (uniqueness is per grower).
        grove_b = validate_success(api_client.create_grove(
            create_grove_payload(grower_b["id"], "B1", "VALENCIA", 20, "POLK"), ADMIN),
            expected_status=201)
        assert_grove(grove_b)


class TestPoolAndChannelCreation:
    def test_pool_duplicate_variety_week_rejected(self, api):
        """PRD §3.6: "A `PoolAccountant` opens a weekly pool by supplying a
        `variety` and a `week_start` — the Monday date in YYYY-MM-DD form; the
        pair of variety and week must be unique (`ERR_DUPLICATE_ENTITY`)."

        Design: Corner/entities/pool_duplicate_variety_week_rejected
        """
        validate_success(api_client.create_pool(
            create_pool_payload("HAMLIN", "2026-07-27"), ACCOUNTANT),
            expected_status=201)
        resp = api_client.create_pool(create_pool_payload("HAMLIN", "2026-07-27"),
                                      ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTITY)
        # The same variety in a different week is a distinct pool.
        other = validate_success(api_client.create_pool(
            create_pool_payload("HAMLIN", "2026-08-03"), ACCOUNTANT),
            expected_status=201)
        assert other["week_start"] == "2026-08-03"

    def test_channel_market_type_coherence(self, api):
        """PRD §3.5: a channel carries "a `destination_market` — which must be
        `JAPAN`, `EU`, or `KOREA` for an `EXPORT` channel, `DOMESTIC` for a
        `DOMESTIC_FRESH` channel, and `NONE` for a `JUICE` channel, with an
        inconsistent pairing rejected as `ERR_INVALID_REQUEST`". PRD §3.5:
        "A channel's `remaining_boxes` is its `allocation_boxes` minus the
        boxes already allocated to `POSTED` runs; juice channels are uncapped
        and report null for `remaining_boxes`."

        Design: Corner/entities/channel_market_type_coherence
        """
        set_clock(DEFAULT_CLOCK)
        bad = api_client.create_channel(
            create_channel_payload("BAD-1", "JUICE", "JAPAN", "HAMLIN",
                                   allocation_boxes=0, price_cents_per_box=220,
                                   priority_rank=9, accepts_grades=("JUICE",)), ADMIN)
        validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)
        good = validate_success(api_client.create_channel(
            create_channel_payload("OK-1", "EXPORT", "KOREA", "HAMLIN",
                                   allocation_boxes=10, price_cents_per_box=800,
                                   priority_rank=1, accepts_grades=("FANCY",)), ADMIN),
            expected_status=201)
        assert_channel(good)
        assert good["remaining_boxes"] == 10, "no posted runs yet: full capacity remains"


class TestResponseEnvelope:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter sets the number of items
        skipped and defaults to 0." and "The `meta` object of a list response
        carries the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/list_pagination_envelope
        """
        for i in range(1, 4):
            validate_success(api_client.create_grower(
                create_grower_payload(f"GR-PG{i}", f"P{i}"), ADMIN), expected_status=201)
        page1, meta1 = validate_paginated(
            api_client.list_growers(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0
        assert isinstance(meta1["api_request_id"], str)
        assert is_iso8601_timestamp(meta1["api_request_timestamp"])
        page2, meta2 = validate_paginated(
            api_client.list_growers(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: \"error\"" and a data
        object in which "The `error_id` is a unique, machine-readable string
        that identifies the specific error" and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        set_clock(DEFAULT_CLOCK)
        resp = api_client.get_pool(NON_EXISTENT_UUID, ACCOUNTANT)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert isinstance(error_data["message"], str) and error_data["message"].strip()
