"""Baseline envelope, creation defaults, malformed-input, and pagination claims."""
import re

from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    NON_EXISTENT_UUID,
    OWNER,
    advance_season_to,
    bucket_of,
    create_block,
    create_buyer,
    create_draft_order,
    create_season,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    setup_booking_season,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    make_buyer_headers,
)


class TestSeasonCreationDefaults:
    def test_season_born_planning_with_zero_ops_index(self, api):
        """PRD §3.1: "A new season is born in `PLANNING` posture with its
        `ops_run_index` at zero."

        Design: Corner/entities/season_create_applies_defaults
        """
        resp = api.create_season(
            {
                "year": 2026,
                "booking_open_at": "2026-06-01T00:00:00Z",
                "booking_close_at": "2026-08-31T23:59:59Z",
                "harvest_window_start": "2026-11-01",
                "harvest_window_end": "2026-11-25",
                "shipping_window_start": "2026-11-15T00:00:00Z",
                "shipping_window_end": "2026-12-10T23:59:59Z",
            },
            OWNER,
        )
        season = validate_success(resp, expected_status=201)
        assert season["posture"] == "PLANNING"
        assert season["ops_run_index"] == 0
        assert season["version"] == 1
        # Re-read proves the state persisted, not just echoed.
        reread = validate_success(api.get_season(season["id"], OWNER))
        assert reread["posture"] == "PLANNING"
        assert reread["ops_run_index"] == 0
        assert reread["version"] == 1

    def test_season_common_fields_uuid_and_millisecond_timestamp(self, api):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier for the
        resource, formatted as a UUID with no type prefix."
        PRD §2.5: "`created_at` (string): an ISO 8601 timestamp in UTC with
        three fractional digits (for example, 2025-05-24T10:30:00.123Z), set
        when the resource is first created."

        Design: Corner/entities/season_create_applies_defaults
        """
        season = create_season()
        assert is_valid_uuid(season["id"]), "id must be a bare UUID"
        assert re.search(r"\.\d{3}", season["created_at"]), (
            f"created_at must carry three fractional digits: {season['created_at']}"
        )
        assert is_iso8601_timestamp(season["created_at"])
        assert is_iso8601_timestamp(season["updated_at"])


class TestBlockCreationDefaults:
    def test_block_system_fields_are_server_controlled(self, api):
        """PRD §2.5: "`version` (integer): starts at 1 at creation and
        increments by exactly 1 on every mutation of the resource, including
        mutations the server applies automatically as side effects of other
        operations."
        PRD §4: "Create a block in `RESTING` rotation".

        Design: Corner/entities/block_create_system_field_input_ignored
        """
        season = create_season()
        supplied_id = "00000000-0000-4000-8000-0000000000aa"
        resp = api.create_block(
            {
                "season_id": season["id"],
                "block_code": "B-9",
                "acreage": 3.0,
                "id": supplied_id,
                "version": 99,
                "rotation_state": "HARVESTED",
            },
            FM,
        )
        block = validate_success(resp, expected_status=201)
        assert block["id"] != supplied_id, "server must mint its own id"
        assert is_valid_uuid(block["id"])
        assert block["version"] == 1, "version starts at 1, client 99 ignored"
        assert block["rotation_state"] == "RESTING"

    def test_block_ucut_designated_defaults_false(self, api):
        """PRD §3.1: "A block flagged `ucut_designated` (defaulting to false
        when omitted) is open to choose-and-cut retail customers once
        harvestable."

        Design: Corner/entities/block_create_system_field_input_ignored
        """
        season = create_season()
        block = create_block(season["id"], block_code="B-7", acreage=2.0)
        assert block["ucut_designated"] is False


class TestNotFound:
    def test_get_order_with_unknown_id_returns_404(self, api):
        """PRD §2.6: "For any request whose path contains resource identifiers,
        and for any foreign-key reference carried in a request body, the system
        validates existence in a strict left-to-right order and rejects with
        `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        correspond to an existing resource."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        create_season()
        resp = api.get_order(NON_EXISTENT_UUID, OWNER)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip()

    def test_not_found_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, OWNER)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["data"].get("error_id"), str)
        assert isinstance(body["data"].get("message"), str)


class TestOrderCreateMalformed:
    def _booking_with_buyer(self):
        season = create_season()
        set_clock(CLOCK["BOOKING_OPEN"])
        advance_season_to(season["id"], "BOOKING")
        buyer = create_buyer()
        return season, buyer

    def test_missing_quantity_returns_400(self, api):
        """PRD §2.6: "A request body that is missing a required field, carries
        a value of the wrong type, names an enum member outside the declared
        set, or supplies a quantity below its minimum is rejected with
        `ERR_MALFORMED_REQUEST` (HTTP 400)."
        PRD §3.3: "Creating a **WholesaleOrder** names the `season_id`, the
        `buyer_account_id` (which must equal the caller's `X-User-ID`, else
        `ERR_FORBIDDEN`), the `species`, the `height_class`, the `quantity` of
        trees (at least one), and the agreed `unit_price_cents` (at least
        zero)."

        Design: Corner/entities/order_create_missing_required_quantity_returns_400
        """
        season, buyer = self._booking_with_buyer()
        resp = api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "NOBLE_FIR",
                "height_class": "H_6_7",
                "unit_price_cents": 400,
            },
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MALFORMED_REQUEST)

    def test_missing_quantity_persists_nothing(self, api):
        """PRD §2.6: "A request body that is missing a required field, carries
        a value of the wrong type, names an enum member outside the declared
        set, or supplies a quantity below its minimum is rejected with
        `ERR_MALFORMED_REQUEST` (HTTP 400)."

        Design: Corner/entities/order_create_missing_required_quantity_returns_400
        """
        season, buyer = self._booking_with_buyer()
        api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "NOBLE_FIR",
                "height_class": "H_6_7",
                "unit_price_cents": 400,
            },
            make_buyer_headers(buyer["id"]),
        )
        data, meta = validate_paginated(
            api.list_orders(FM, params={"buyer_account_id": buyer["id"]})
        )
        assert meta["total_count"] == 0, "rejected create must persist nothing"

    def test_invalid_species_enum_returns_400(self, api):
        """PRD §2.8: "species are exactly `NOBLE_FIR`, `DOUGLAS_FIR`,
        `GRAND_FIR`, and `NORDMANN_FIR`."
        PRD §2.6: "A request body that is missing a required field, carries a
        value of the wrong type, names an enum member outside the declared set,
        or supplies a quantity below its minimum is rejected with
        `ERR_MALFORMED_REQUEST` (HTTP 400)."

        Design: Corner/entities/order_create_invalid_enum_species_rejected
        """
        season, buyer = self._booking_with_buyer()
        resp = api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "PINE_42",
                "height_class": "H_6_7",
                "quantity": 5,
                "unit_price_cents": 400,
            },
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MALFORMED_REQUEST)
        data, meta = validate_paginated(
            api.list_orders(FM, params={"buyer_account_id": buyer["id"]})
        )
        assert meta["total_count"] == 0

    def test_valid_species_accepted(self, api):
        """PRD §2.8: "species are exactly `NOBLE_FIR`, `DOUGLAS_FIR`,
        `GRAND_FIR`, and `NORDMANN_FIR`."

        Design: Corner/entities/order_create_invalid_enum_species_rejected
        """
        season, buyer = self._booking_with_buyer()
        order = create_draft_order(
            season["id"], buyer["id"], species="NOBLE_FIR", quantity=5,
            unit_price_cents=400,
        )
        assert order["species"] == "NOBLE_FIR"
        assert order["status"] == "DRAFT"

    def test_computed_allocated_qty_input_ignored(self, api):
        """PRD §3.3: "Orders are born `DRAFT` with `allocated_qty` at zero;
        creation outside `BOOKING` is refused with `ERR_POSTURE_FORBIDS`."

        Design: Corner/entities/order_create_computed_field_input_ignored
        """
        season, buyer = self._booking_with_buyer()
        resp = api.create_order(
            {
                "season_id": season["id"],
                "buyer_account_id": buyer["id"],
                "species": "NOBLE_FIR",
                "height_class": "H_6_7",
                "quantity": 5,
                "unit_price_cents": 400,
                "allocated_qty": 999,
            },
            make_buyer_headers(buyer["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert order["allocated_qty"] == 0, "client-supplied 999 must be ignored"
        assert order["status"] == "DRAFT"


class TestBlockListPagination:
    def test_limit_offset_windowing_and_total_count(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/block_list_pagination_envelope
        """
        season = create_season()
        for code, acres in (("B-1", 5.0), ("B-2", 6.0), ("B-3", 7.0)):
            create_block(season["id"], block_code=code, acreage=acres)
        page1, meta1 = validate_paginated(
            api.list_blocks(FM, params={"season_id": season["id"], "limit": 2})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_blocks(
                FM, params={"season_id": season["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_created_at_ascending_order(self, api):
        """PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."
        PRD §3.1: "The block list can be filtered by `season_id`."

        Design: Corner/entities/block_list_pagination_envelope
        """
        season = create_season()
        for code in ("B-1", "B-2", "B-3"):
            create_block(season["id"], block_code=code, acreage=5.0)
        page1, _ = validate_paginated(
            api.list_blocks(FM, params={"season_id": season["id"], "limit": 2})
        )
        page2, _ = validate_paginated(
            api.list_blocks(
                FM, params={"season_id": season["id"], "limit": 2, "offset": 2}
            )
        )
        assert [b["block_code"] for b in page1] == ["B-1", "B-2"]
        assert [b["block_code"] for b in page2] == ["B-3"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request that arrives without these headers, or carrying
        an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/errors/missing_auth_headers_returns_401
        """
        season = create_season()
        resp = api.get_season(season["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unauthenticated_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/missing_auth_headers_returns_401
        """
        season = create_season()
        resp = api.get_season(season["id"], headers={})
        body = resp.json()
        assert resp.status_code == 401
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
