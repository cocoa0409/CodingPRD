"""Body validation, reference resolution and collection windowing on the
entities.

The two module-local fixtures build the multi-stop state that three of these
tests need. They are function-scoped on purpose: the server is restarted against
an empty database before every test, so no state may be shared across tests.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_marketing_allocation,
    assert_pagination_meta,
    assert_ticket_order,
    assert_vehicle_entry,
    constants as C,
    fixtures as helpers,
    make_marketing_allocation_payload,
    make_ticket_order_payload,
    make_vehicle_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_SECOND_TIER_ON_SALE_END_UTC = "2026-12-05T18:00:00Z"


@pytest.fixture
def two_market_price_cards(api: ApiClient) -> Dict[str, Any]:
    """One on-sale stop in the primary market and a second stop, in another
    market of the same season, carrying its own pricing tier."""
    primary = helpers.stop_on_sale(api)
    secondary = helpers.stop_with_show_timing(
        api,
        season_id=primary["season_id"],
        venue_name=C.SECOND_VENUE_NAME,
        market_code=C.SECOND_VENUE_MARKET_CODE,
        city=C.SECOND_VENUE_CITY,
        state_code=C.SECOND_VENUE_STATE_CODE,
        tour_date=C.SECOND_TOUR_DATE,
        load_in_start_utc=C.SECOND_LOAD_IN_START_UTC,
        tear_down_end_utc=C.SECOND_TEAR_DOWN_END_UTC,
        doors_open_utc=C.SECOND_DOORS_OPEN_UTC,
        show_start_utc=C.SECOND_SHOW_START_UTC,
    )
    foreign = helpers.create_ticket_tier(
        api,
        secondary["stop_id"],
        on_sale_end_utc=_SECOND_TIER_ON_SALE_END_UTC,
    )
    return {
        "stop_id": primary["stop_id"],
        "tier_id": primary["tier_id"],
        "foreign_stop_id": secondary["stop_id"],
        "foreign_tier_id": foreign["tier_id"],
    }


@pytest.fixture
def three_market_stops(api: ApiClient) -> Dict[str, Any]:
    """Three confirmed stops of one season, in three different markets."""
    first = helpers.confirmed_booking(api)
    season_id = first["season_id"]
    second = helpers.confirmed_booking(
        api,
        season_id=season_id,
        venue_name=C.SECOND_VENUE_NAME,
        market_code=C.SECOND_VENUE_MARKET_CODE,
        city=C.SECOND_VENUE_CITY,
        state_code=C.SECOND_VENUE_STATE_CODE,
        tour_date=C.SECOND_TOUR_DATE,
        load_in_start_utc=C.SECOND_LOAD_IN_START_UTC,
        tear_down_end_utc=C.SECOND_TEAR_DOWN_END_UTC,
    )
    third = helpers.confirmed_booking(
        api,
        season_id=season_id,
        venue_name=C.THIRD_VENUE_NAME,
        market_code=C.THIRD_VENUE_MARKET_CODE,
        city=C.THIRD_VENUE_CITY,
        state_code=C.THIRD_VENUE_STATE_CODE,
        tour_date=C.THIRD_TOUR_DATE,
        load_in_start_utc=C.THIRD_LOAD_IN_START_UTC,
        tear_down_end_utc=C.THIRD_TEAR_DOWN_END_UTC,
    )
    return {
        "season_id": season_id,
        "stop_ids": [first["stop_id"], second["stop_id"], third["stop_id"]],
    }


class TestVehicleEntryRequiredFields:
    """A body missing a mandatory field never reaches the domain rules."""

    def test_vehicle_entry_without_the_race_weight_is_rejected(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        competitor: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """Omitting `vehicle_weight_lbs` is a 422 and writes no entry row.

        PRD §3.3: "Entering a vehicle in a stop names the `competitor_id` and the
        `tour_stop_id`, the `vehicle_number` as painted on the body, the race
        weight as `vehicle_weight_lbs` (at least 1), the `haul_distance_miles` the
        transporter will cover to reach this stop (zero or more), and the promised
        transporter ETA as `scheduled_arrival_utc`."

        PRD §2.10: "`ERR_INVALID_REQUEST` (422) — a required body field is
        missing, a scalar has the wrong type, a date or datetime is malformed, an
        enum value falls outside its declared set, a quantity, amount or count
        falls below its declared minimum, `limit` is outside 1 through 100, or
        `offset` is negative. Every endpoint with a body or query parameters."

        Design: Corner/entities/corner_missing_required_field_on_vehicle_entry_is_rejected
        """
        stop_id = confirmed_booking["stop_id"]
        payload = make_vehicle_entry_payload(
            competitor["competitor_id"], stop_id, vehicle_weight_lbs=None
        )
        assert "vehicle_weight_lbs" not in payload

        response = api.create_vehicle_entry(payload, headers=promoter_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)

        rows, meta = validate_paginated(
            api.list_vehicle_entries(
                params={"tour_stop_id": stop_id}, headers=promoter_headers
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_rejected_entry_consumed_no_staging_bay(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        competitor: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """After the rejection the bay pool is untouched, so the next well-formed
        light rig takes the lowest bay index.

        PRD §2.10: "`ERR_INVALID_REQUEST` (422) — a required body field is
        missing, a scalar has the wrong type, a date or datetime is malformed, an
        enum value falls outside its declared set, a quantity, amount or count
        falls below its declared minimum, `limit` is outside 1 through 100, or
        `offset` is negative. Every endpoint with a body or query parameters."

        PRD §3.3: "The choice within the candidate set depends on weight: an entry
        whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and
        takes the **highest** free bay index, staging nearest the ramp, while a
        lighter rig takes the **lowest** free index, staging from the far wall."

        Design: Corner/entities/corner_missing_required_field_on_vehicle_entry_is_rejected
        """
        stop_id = confirmed_booking["stop_id"]
        validate_error(
            api.create_vehicle_entry(
                make_vehicle_entry_payload(
                    competitor["competitor_id"], stop_id, vehicle_weight_lbs=None
                ),
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=422,
        )

        entry = validate_success(
            api.create_vehicle_entry(
                make_vehicle_entry_payload(competitor["competitor_id"], stop_id),
                headers=promoter_headers,
            ),
            expected_status=201,
        )

        assert_vehicle_entry(entry)
        assert entry["vehicle_weight_lbs"] == C.DEFAULT_VEHICLE_WEIGHT_LBS
        assert entry["staging_bay_index"] == 1


class TestMarketingAllocationFieldConstraints:
    """The allocation body is checked against its enum and its minimum."""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"channel": "PRINT", "amount_cents": 500000},
            {"channel": "RADIO", "amount_cents": 0},
        ],
        ids=["channel-outside-the-declared-set", "amount-below-its-minimum"],
    )
    def test_marketing_allocation_body_constraints_are_enforced(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
        overrides: Dict[str, Any],
    ) -> None:
        """A channel outside the declared set and an amount below its minimum are
        both rejected with the same shape error.

        PRD §3.9: "An allocation names the stop through `tour_stop_id`, a
        `channel` of `RADIO`, `DIGITAL` or `GRASSROOTS`, an `amount_cents` of at
        least 1, and the season concurrency token `expected_season_version` from
        §2.7."

        PRD §2.10: "`ERR_INVALID_REQUEST` (422) — a required body field is
        missing, a scalar has the wrong type, a date or datetime is malformed, an
        enum value falls outside its declared set, a quantity, amount or count
        falls below its declared minimum, `limit` is outside 1 through 100, or
        `offset` is negative. Every endpoint with a body or query parameters."

        Design: Corner/entities/corner_enum_and_minimum_constraints_rejected_on_marketing_allocation
        """
        version = helpers.fetch_season_version(api, confirmed_booking["season_id"])

        response = api.create_marketing_allocation(
            confirmed_booking["stop_id"],
            make_marketing_allocation_payload(version, **overrides),
            headers=promoter_headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)

    def test_rejected_allocations_leave_the_season_ledger_and_token_intact(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """Neither rejection spent money or advanced the season version, so the
        same token still commits a well-formed allocation.

        PRD §3.9: "A committed allocation opens in `state` `COMMITTED` with
        `released_at` null."

        PRD §2.7: "The season's `marketing_unallocated_cents` is the single pool
        every market draws from, and its `version` advances on every commit and
        every release, so a stale value means the client may be planning against
        money another market has already committed or handed back."

        Design: Corner/entities/corner_enum_and_minimum_constraints_rejected_on_marketing_allocation
        """
        season_id = confirmed_booking["season_id"]
        stop_id = confirmed_booking["stop_id"]
        before = helpers.fetch_season(api, season_id)
        version = before["version"]

        for overrides in (
            {"channel": "PRINT", "amount_cents": 500000},
            {"channel": "RADIO", "amount_cents": 0},
        ):
            validate_error(
                api.create_marketing_allocation(
                    stop_id,
                    make_marketing_allocation_payload(version, **overrides),
                    headers=promoter_headers,
                ),
                ApiErrorId.ERR_INVALID_REQUEST,
                expected_status=422,
            )

        untouched = helpers.fetch_season(api, season_id)
        assert untouched["version"] == version
        assert untouched["marketing_allocated_cents"] == 0
        assert untouched["marketing_unallocated_cents"] == before["marketing_unallocated_cents"]

        allocation = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    version, channel="RADIO", amount_cents=500000
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )

        assert_marketing_allocation(allocation)
        assert allocation["state"] == "COMMITTED"
        assert allocation["channel"] == "RADIO"
        assert allocation["amount_cents"] == 500000
        assert allocation["tour_stop_id"] == stop_id


class TestUnknownPathIdentifier:
    """An unresolvable path id answers the 404 of the addressed entity."""

    @pytest.mark.parametrize(
        "target, expected_error",
        [
            ("venue_booking", ApiErrorId.ERR_VENUE_BOOKING_NOT_FOUND),
            ("settlement", ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
            ("vehicle_entry", ApiErrorId.ERR_VEHICLE_ENTRY_NOT_FOUND),
        ],
    )
    def test_unknown_path_id_returns_the_entity_specific_not_found(
        self,
        api: ApiClient,
        season: Dict[str, Any],
        promoter_headers: Dict[str, str],
        finance_controller_headers: Dict[str, str],
        target: str,
        expected_error: ApiErrorId,
    ) -> None:
        """Each read of a well-formed but unknown id names its own entity in the
        error envelope.

        PRD §2.6: "The first identifier that does not resolve determines the
        error, and the response is the 404 belonging to that entity —
        `ERR_SEASON_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
        `ERR_VENUE_BOOKING_NOT_FOUND`, `ERR_TOUR_STOP_NOT_FOUND`,
        `ERR_COMPETITOR_NOT_FOUND`, `ERR_VEHICLE_ENTRY_NOT_FOUND`,
        `ERR_TECH_INSPECTION_NOT_FOUND`, `ERR_SHOW_SEGMENT_NOT_FOUND`,
        `ERR_TICKET_TIER_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND`,
        `ERR_SPONSOR_NOT_FOUND`, `ERR_SPONSORSHIP_ACTIVATION_NOT_FOUND`,
        `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_MARKETING_ALLOCATION_NOT_FOUND` or
        `ERR_SETTLEMENT_NOT_FOUND`."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/corner_unknown_path_id_returns_the_entity_specific_not_found
        """
        assert season["season_id"] != NON_EXISTENT_UUID

        reads = {
            "venue_booking": lambda: api.get_venue_booking(
                NON_EXISTENT_UUID, headers=promoter_headers
            ),
            "settlement": lambda: api.get_settlement(
                NON_EXISTENT_UUID, headers=finance_controller_headers
            ),
            "vehicle_entry": lambda: api.get_vehicle_entry(
                NON_EXISTENT_UUID, headers=promoter_headers
            ),
        }
        response = reads[target]()

        error = validate_error(response, expected_error, expected_status=404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""


class TestTicketOrderBodyReferences:
    """Body foreign keys on an order: resolution first, then the parent match."""

    def test_unresolvable_tier_reference_is_the_tier_not_found(
        self,
        api: ApiClient,
        two_market_price_cards: Dict[str, Any],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """A `ticket_tier_id` that resolves to nothing answers the tier's own 404.

        PRD §2.6: "Foreign keys supplied in a request body are resolved with the
        same entity-specific 404s, immediately after path resolution and before
        any state or business rule is evaluated."

        PRD §2.6: "The body keys that are resolved this way are `season_id`,
        `venue_id`, `competitor_id`, `tour_stop_id`, `ticket_tier_id`,
        `sponsor_id`, `hospitality_tier_id`, `branded_vehicle_entry_id`,
        `featured_vehicle_entry_id` and `preceding_stop_id`."

        Design: Corner/entities/corner_flat_topology_fk_integrity_on_ticket_order_body_references
        """
        stop_id = two_market_price_cards["stop_id"]
        version = helpers.fetch_tier_version(api, two_market_price_cards["tier_id"])

        response = api.create_ticket_order(
            make_ticket_order_payload(stop_id, NON_EXISTENT_UUID, version),
            headers=ticketing_headers,
        )

        validate_error(
            response, ApiErrorId.ERR_TICKET_TIER_NOT_FOUND, expected_status=404
        )

    def test_tier_belonging_to_another_stop_is_a_child_stop_mismatch(
        self,
        api: ApiClient,
        two_market_price_cards: Dict[str, Any],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """A resolvable tier that hangs off a different stop is rejected, and its
        own seat pool is left alone.

        PRD §3.7: "The named tier must belong to the named stop, or the order is
        rejected with `ERR_CHILD_STOP_MISMATCH`."

        Design: Corner/entities/corner_flat_topology_fk_integrity_on_ticket_order_body_references
        """
        stop_id = two_market_price_cards["stop_id"]
        foreign_tier_id = two_market_price_cards["foreign_tier_id"]
        foreign_version = helpers.fetch_tier_version(api, foreign_tier_id)

        response = api.create_ticket_order(
            make_ticket_order_payload(stop_id, foreign_tier_id, foreign_version),
            headers=ticketing_headers,
        )

        validate_error(
            response, ApiErrorId.ERR_CHILD_STOP_MISMATCH, expected_status=422
        )

        foreign_tier = helpers.fetch_tier(api, foreign_tier_id)
        assert foreign_tier["tour_stop_id"] == two_market_price_cards["foreign_stop_id"]
        assert foreign_tier["reserved_seat_count"] == 0
        assert foreign_tier["available_seat_count"] == foreign_tier["allotment"]

    def test_a_tier_of_the_named_stop_is_accepted(
        self,
        api: ApiClient,
        two_market_price_cards: Dict[str, Any],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """The matching stop-and-tier pair places a pending order.

        PRD §3.7: "The named tier must belong to the named stop, or the order is
        rejected with `ERR_CHILD_STOP_MISMATCH`."

        PRD §3.7: "A created order opens with `status` `PENDING`, `paid_at`,
        `refunded_at` and `void_reason` all null; its `qty` is added to the tier's
        `reserved_seat_count`, `available_seat_count` falls by the same amount,
        and the tier's `version` increments by one — which is exactly why the next
        client to write against that tier needs a fresh
        `expected_ticket_tier_version`."

        Design: Corner/entities/corner_flat_topology_fk_integrity_on_ticket_order_body_references
        """
        stop_id = two_market_price_cards["stop_id"]
        tier_id = two_market_price_cards["tier_id"]
        version = helpers.fetch_tier_version(api, tier_id)

        order = validate_success(
            api.create_ticket_order(
                make_ticket_order_payload(stop_id, tier_id, version),
                headers=ticketing_headers,
            ),
            expected_status=201,
        )

        assert_ticket_order(order)
        assert order["status"] == "PENDING"
        assert order["tour_stop_id"] == stop_id
        assert order["ticket_tier_id"] == tier_id


class TestTourStopCollection:
    """The stop collection's window, its filter and its rejected limit."""

    def test_tour_stop_pages_report_the_window_and_do_not_overlap(
        self,
        api: ApiClient,
        three_market_stops: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """Two pages of two cover three stops without repeating a row.

        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
        may not be smaller than 1 and may not be larger than 100."

        PRD §2.3: "`offset` skips rows before the page begins; it defaults to 0
        and may not be negative."

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` in the envelope's `meta` object."

        Design: Corner/entities/corner_tour_stop_listing_paginates_and_filters
        """
        assert len(three_market_stops["stop_ids"]) == 3

        first_rows, first_meta = validate_paginated(
            api.list_tour_stops(params={"limit": 2, "offset": 0}, headers=promoter_headers)
        )
        assert len(first_rows) == 2
        assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3)
        assert first_meta["has_more"] is True

        second_rows, second_meta = validate_paginated(
            api.list_tour_stops(params={"limit": 2, "offset": 2}, headers=promoter_headers)
        )
        assert len(second_rows) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3)
        assert second_meta["has_more"] is False

        assert first_rows[0]["id"] != second_rows[0]["id"]
        page_ids = {row["id"] for row in first_rows} | {row["id"] for row in second_rows}
        assert page_ids == set(three_market_stops["stop_ids"])

    def test_market_code_filter_narrows_the_stop_collection(
        self,
        api: ApiClient,
        three_market_stops: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """Filtering on the market returns only that market's stop.

        PRD §2.3: "Tour-stop lists accept `season_id`, `venue_booking_id`,
        `preceding_stop_id`, `market_code` and `sales_state`."

        Design: Corner/entities/corner_tour_stop_listing_paginates_and_filters
        """
        rows, meta = validate_paginated(
            api.list_tour_stops(
                params={"market_code": C.SECOND_VENUE_MARKET_CODE},
                headers=promoter_headers,
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["market_code"] == C.SECOND_VENUE_MARKET_CODE
        assert rows[0]["id"] in three_market_stops["stop_ids"]

    def test_a_limit_above_the_maximum_is_rejected(
        self,
        api: ApiClient,
        three_market_stops: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """A limit of 101 is outside the accepted range.

        PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
        `offset`, is rejected with `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/corner_tour_stop_listing_paginates_and_filters
        """
        response = api.list_tour_stops(
            params={"limit": C.MAX_PAGE_LIMIT + 1}, headers=promoter_headers
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)
