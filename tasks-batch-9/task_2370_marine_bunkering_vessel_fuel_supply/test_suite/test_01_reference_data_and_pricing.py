"""Reference data: ports, grades, the price index and the delivery fleet.

Nothing can be nominated until these rows exist, and the shapes they take are
load-bearing later. Optional inputs must fall back to declared defaults rather
than nulls, reference codes are unique, index quotes are immutable and carry no
version at all, and every persisted timestamp is drawn from the logical clock
rather than from the host.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH,
    COMPLIANCE,
    CREDIT,
    OPS,
    add_asset,
    add_fuel_grade,
    add_index_quote,
    add_port,
    api_client,
    assert_created_at_ascending,
    assert_delivery_asset,
    assert_fuel_grade,
    assert_index_quote,
    assert_port,
    assert_quote_date_descending,
    create_fuel_grade_payload,
    create_port_payload,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_CLOCK = "2026-08-05T09:15:00Z"


class TestPortRegistration:
    """The operational record every slot and clearance hangs off."""

    def test_a_fully_specified_port_echoes_every_declared_field(self):
        """PRD §3.1: "A port is registered with an operational `port_code` used on
        clearance paperwork — between 1 and 16 characters, unique across all ports,
        with a collision rejected as `ERR_DUPLICATE_REFERENCE_CODE` — and a
        human-readable `name`."
        PRD §3.1: "Finally `spill_response_tier` records the port's contracted
        response capability as `TIER_1`, `TIER_2` or `TIER_3`, defaulting to
        `TIER_2`."
        PRD §2.5: "`version`, an integer that starts at 1 on creation and increments
        by one on every mutation of the record."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/entities/port_creation_returns_all_declared_fields
        """
        set_logical_clock(CLOCK_EPOCH)

        port = validate_success(
            api_client.create_port(create_port_payload(), OPS), 201
        )

        assert_port(port)
        assert port["port_code"] == "NLRTM", (
            f"Expected NLRTM, got {port['port_code']}"
        )
        assert port["name"] == "Rotterdam", f"Expected Rotterdam, got {port['name']}"
        assert port["eca_zone"] is True, (
            f"The supplied emission-control flag must survive, got {port['eca_zone']}"
        )
        assert port["eca_sulfur_limit_pct"] == pytest.approx(0.100, abs=0.0005), (
            f"Expected 0.100, got {port['eca_sulfur_limit_pct']}"
        )
        assert port["notice_lead_hours"] == 24, (
            f"Expected 24, got {port['notice_lead_hours']}"
        )
        assert port["concurrent_ops_capacity"] == 2, (
            f"Expected 2, got {port['concurrent_ops_capacity']}"
        )
        assert port["spill_response_tier"] == "TIER_1", (
            f"The supplied tier must survive, got {port['spill_response_tier']}"
        )
        assert port["version"] == 1, (
            f"A fresh record opens at version 1, got {port['version']}"
        )
        assert port["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at takes the logical clock, got {port['created_at']}"
        )

    def test_omitted_optional_fields_take_their_declared_defaults(self):
        """PRD §3.1: "Its emission-control profile is optional at registration:
        `eca_zone` defaults to false and `eca_sulfur_limit_pct` to 0.100 mass percent,
        recorded to three decimal places and required to be strictly greater than
        zero."
        PRD §3.1: "`notice_lead_hours` is the minimum number of hours that must elapse
        between now and the start of any delivery slot at the port, and defaults to a
        full day, that is 24 hours; it may be zero but never negative."
        PRD §3.1: "`concurrent_ops_capacity` caps how many delivery orders may hold
        overlapping slots at the port simultaneously and defaults to 2, with a floor of
        1."

        Design: Corner/entities/port_defaults_applied_when_optional_fields_omitted
        """
        set_logical_clock(CLOCK_EPOCH)

        port = validate_success(
            api_client.create_port({"port_code": "SGSIN", "name": "Singapore"}, OPS),
            201,
        )

        assert_port(port)
        assert port["eca_zone"] is False, (
            f"eca_zone defaults to false, got {port['eca_zone']}"
        )
        assert port["eca_sulfur_limit_pct"] == pytest.approx(0.100, abs=0.0005), (
            f"eca_sulfur_limit_pct defaults to 0.100, got "
            f"{port['eca_sulfur_limit_pct']}"
        )
        assert port["notice_lead_hours"] == 24, (
            f"notice_lead_hours defaults to a full day, got {port['notice_lead_hours']}"
        )
        assert port["concurrent_ops_capacity"] == 2, (
            f"concurrent_ops_capacity defaults to 2, got "
            f"{port['concurrent_ops_capacity']}"
        )
        assert port["spill_response_tier"] == "TIER_2", (
            f"spill_response_tier defaults to TIER_2, got "
            f"{port['spill_response_tier']}"
        )

    def test_a_repeated_port_code_collides_whatever_the_display_name(self):
        """PRD §3.1: "A port is registered with an operational `port_code` used on
        clearance paperwork — between 1 and 16 characters, unique across all ports,
        with a collision rejected as `ERR_DUPLICATE_REFERENCE_CODE` — and a
        human-readable `name`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        number of records matching the filter before pagination is applied and
        `has_more` indicates whether records remain beyond the current page."

        Uniqueness is on the code alone, so a second Rotterdam terminal under a
        different display name is still a collision.

        Design: Corner/validations/duplicate_port_code_rejected
        """
        set_logical_clock(CLOCK_EPOCH)
        first = add_port()

        response = api_client.create_port(
            create_port_payload(name="Rotterdam Europoort"), OPS
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_REFERENCE_CODE)
        ports, meta = validate_paginated(api_client.list_ports(OPS))
        assert meta["total_count"] == 1, (
            f"The collision must persist nothing, got {meta['total_count']} ports"
        )
        assert ports[0]["id"] == first["id"], (
            "The surviving row must be the original, got a different id"
        )
        assert ports[0]["name"] == "Rotterdam", (
            f"The original display name must be intact, got {ports[0]['name']}"
        )


class TestFuelGradeRegistration:
    """The contractual sulfur ceiling, the barging tariff and the segregation family."""

    def test_a_grade_reads_back_exactly_as_it_was_stored(self):
        """PRD §3.1: "A fuel grade is registered with a `grade_code` such as MGO-DMA or
        VLSFO-RME, unique across grades and likewise rejected with
        `ERR_DUPLICATE_REFERENCE_CODE` on collision, together with its contractual
        `max_sulfur_pct` ceiling to three decimal places and strictly positive."
        PRD §3.1: "Commercially, `base_barging_rate_usd_per_mt` gives the barging or
        trucking rate in dollars per metric tonne and `min_barging_fee_usd` the floor
        applied to the resulting fee, both to two decimals and both non-negative."
        PRD §3.1: "`cross_contamination_group` places the grade in a segregation family
        — `DISTILLATE`, `RESIDUAL` or `BIOBLEND` — which later determines whether a
        barge that last carried something else needs segregated tanks."

        Design: Corner/entities/fuel_grade_retrieval_returns_stored_row
        """
        set_logical_clock(CLOCK_EPOCH)
        created = add_fuel_grade()

        grade = validate_success(api_client.get_fuel_grade(created["id"], COMPLIANCE))

        assert_fuel_grade(grade)
        assert grade["grade_code"] == "MGO-DMA", (
            f"Expected MGO-DMA, got {grade['grade_code']}"
        )
        assert grade["max_sulfur_pct"] == pytest.approx(0.100, abs=0.0005), (
            f"Expected 0.100, got {grade['max_sulfur_pct']}"
        )
        assert grade["test_tolerance_pct"] == pytest.approx(0.010, abs=0.0005), (
            f"Expected 0.010, got {grade['test_tolerance_pct']}"
        )
        assert grade["eca_permitted"] is True, (
            f"Expected the grade to be permitted, got {grade['eca_permitted']}"
        )
        assert grade["index_code"] == "MGO-ARA", (
            f"Expected MGO-ARA, got {grade['index_code']}"
        )
        assert grade["base_barging_rate_usd_per_mt"] == pytest.approx(9.50, abs=0.01), (
            f"Expected 9.50, got {grade['base_barging_rate_usd_per_mt']}"
        )
        assert grade["min_barging_fee_usd"] == pytest.approx(2000.00, abs=0.01), (
            f"Expected 2000.00, got {grade['min_barging_fee_usd']}"
        )
        assert grade["cross_contamination_group"] == "DISTILLATE", (
            f"Expected DISTILLATE, got {grade['cross_contamination_group']}"
        )

    def test_a_contamination_family_outside_the_enum_is_refused(self):
        """PRD §3.1: "`cross_contamination_group` places the grade in a segregation
        family — `DISTILLATE`, `RESIDUAL` or `BIOBLEND` — which later determines
        whether a barge that last carried something else needs segregated tanks."
        PRD §2.8: "Payload shape: required fields present, declared types respected,
        enum members valid, declared decimal scales respected, quantities strictly
        positive where declared so, and pagination parameters in range —
        `ERR_INVALID_REQUEST`."

        Nothing may be persisted, which the follow-up create proves by succeeding on
        the same code instead of colliding.

        Design: Corner/entities/fuel_grade_invalid_enum_contamination_group_rejected
        """
        set_logical_clock(CLOCK_EPOCH)

        response = api_client.create_fuel_grade(
            create_fuel_grade_payload(
                grade_code="NAPH-01",
                max_sulfur_pct=0.500,
                eca_permitted=False,
                index_code="NAPH-ARA",
                cross_contamination_group="NAPHTHA",
            ),
            OPS,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        retry = validate_success(
            api_client.create_fuel_grade(
                create_fuel_grade_payload(
                    grade_code="NAPH-01",
                    max_sulfur_pct=0.500,
                    eca_permitted=False,
                    index_code="NAPH-ARA",
                    cross_contamination_group="DISTILLATE",
                ),
                OPS,
            ),
            201,
        )
        assert retry["grade_code"] == "NAPH-01", (
            "The refused create must have left the code free, got "
            f"{retry['grade_code']}"
        )


class TestPriceIndexation:
    """Quotes are append-only, so they carry no version and no updated_at."""

    def test_quote_system_fields_come_from_the_clock_not_the_quote_date(self):
        """PRD §2.5: "Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits recording when the record was first
        written."
        PRD §2.12: "Prices enter the system as immutable `IndexQuote` records, each
        naming the grade it prices through `grade_id`, the instant it becomes effective
        through `quote_date`, its `price_usd_per_mt`, and its publishing agency through
        `source`, which is either `PLATTS` or `ARGUS` and defaults to `PLATTS`."

        The business effective date and the audit timestamp are independent: the quote
        is written on the 1st and becomes effective on the 3rd.

        Design: Corner/entities/index_quote_system_fields_generated
        """
        set_logical_clock(CLOCK_EPOCH)
        grade = add_fuel_grade()

        quote = add_index_quote(grade["id"])

        assert_index_quote(quote)
        assert quote["grade_id"] == grade["id"], (
            f"The quote must name its grade, got {quote['grade_id']}"
        )
        assert quote["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at takes the logical clock, got {quote['created_at']}"
        )
        assert quote["quote_date"].startswith("2026-08-03T00:00:00"), (
            f"The effective date is the supplied one, got {quote['quote_date']}"
        )
        assert quote["price_usd_per_mt"] == pytest.approx(705.00, abs=0.01), (
            f"Expected 705.00, got {quote['price_usd_per_mt']}"
        )
        assert quote["source"] == "PLATTS", (
            f"source defaults to PLATTS, got {quote['source']}"
        )

    def test_a_quote_carries_neither_version_nor_updated_at(self):
        """PRD §2.5: "An `IndexQuote` is immutable once posted. It therefore carries
        only `id` and `created_at`: it has neither `updated_at` nor `version`, and both
        fields are absent from its representation."
        PRD §3.1: "Index quotes are posted by either the operations desk or the credit
        desk and are never amended once written; a correction is made by posting a
        later quote, which is why ties on `quote_date` resolve in favour of the most
        recently created record as described in §2.12."

        Design: Corner/entities/index_quote_has_no_version_field_and_cannot_be_updated
        """
        set_logical_clock(CLOCK_EPOCH)
        grade = add_fuel_grade()
        posted = add_index_quote(grade["id"])

        quotes, meta = validate_paginated(
            api_client.list_grade_index_quotes(grade["id"], CREDIT)
        )

        assert meta["total_count"] == 1, (
            f"Expected exactly one quote, got {meta['total_count']}"
        )
        row = quotes[0]
        assert row["id"] == posted["id"], (
            f"Expected the posted quote, got {row['id']}"
        )
        assert "version" not in row, (
            f"An immutable quote must expose no version, got {row.get('version')}"
        )
        assert "updated_at" not in row, (
            f"An immutable quote must expose no updated_at, got {row.get('updated_at')}"
        )
        assert set(row) == {
            "id", "grade_id", "quote_date", "price_usd_per_mt", "source", "created_at",
        }, f"Unexpected quote representation: {sorted(row)}"

    def test_the_per_grade_listing_pages_over_its_own_quotes_newest_first(self):
        """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
        sorted by `created_at` in ascending order. The one documented exception is the
        per-grade index quote listing, which is ordered by `quote_date` with the most
        recent quote first."
        PRD §3.1: "The quotes for a single grade may be listed on their own, newest
        `quote_date` first, which is how a credit controller reconstructs the
        volatility history behind a bunker adjustment factor."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` inside the `meta` object of the envelope, where `total_count` is the
        number of records matching the filter before pagination is applied and
        `has_more` indicates whether records remain beyond the current page."

        Design: Corner/endpoints/fuel_grade_index_quotes_sub_resource_returns_children
        """
        set_logical_clock("2026-08-10T00:00:00Z")
        grade_a = add_fuel_grade()
        grade_b = add_fuel_grade(
            grade_code="RMG-380",
            max_sulfur_pct=3.500,
            eca_permitted=False,
            test_tolerance_pct=0.050,
            index_code="HSFO-ARA",
            base_barging_rate_usd_per_mt=7.25,
            min_barging_fee_usd=1800.00,
            cross_contamination_group="RESIDUAL",
        )
        add_index_quote(
            grade_a["id"], quote_date="2026-08-01T00:00:00Z", price_usd_per_mt=698.00
        )
        add_index_quote(
            grade_a["id"], quote_date="2026-08-03T00:00:00Z", price_usd_per_mt=705.00
        )
        add_index_quote(
            grade_a["id"], quote_date="2026-08-09T00:00:00Z", price_usd_per_mt=745.50
        )
        add_index_quote(
            grade_b["id"], quote_date="2026-08-05T00:00:00Z", price_usd_per_mt=462.25
        )

        page_one, meta_one = validate_paginated(
            api_client.list_grade_index_quotes(
                grade_a["id"], OPS, params={"limit": 2, "offset": 0}
            )
        )
        page_two, meta_two = validate_paginated(
            api_client.list_grade_index_quotes(
                grade_a["id"], OPS, params={"limit": 2, "offset": 2}
            )
        )
        other_grade, meta_other = validate_paginated(
            api_client.list_grade_index_quotes(
                grade_b["id"], CREDIT, params={"limit": 2, "offset": 0}
            )
        )

        assert meta_one["total_count"] == 3, (
            f"The filtered set has three quotes, got {meta_one['total_count']}"
        )
        assert meta_one["has_more"] is True, (
            "A third quote remains beyond the first page"
        )
        assert [row["price_usd_per_mt"] for row in page_one] == [
            pytest.approx(745.50, abs=0.01),
            pytest.approx(705.00, abs=0.01),
        ], f"Expected the two newest quotes first, got {page_one}"
        assert_quote_date_descending(page_one)
        assert meta_two["total_count"] == 3, (
            f"total_count counts before paging, got {meta_two['total_count']}"
        )
        assert meta_two["has_more"] is False, (
            "The second page exhausts the set"
        )
        assert len(page_two) == 1 and page_two[0]["price_usd_per_mt"] == pytest.approx(
            698.00, abs=0.01
        ), f"Expected the oldest quote alone, got {page_two}"
        assert meta_other["total_count"] == 1, (
            f"The other grade owns one quote, got {meta_other['total_count']}"
        )
        assert other_grade[0]["grade_id"] == grade_b["id"], (
            "The sub-resource must not leak across grades"
        )
        assert all(row["grade_id"] == grade_a["id"] for row in page_one + page_two), (
            "No page of the first grade may carry another grade's quote"
        )


class TestDeliveryFleet:
    """Finding a compatible barge before scheduling by hand."""

    def test_asset_listing_combines_its_filters_with_the_page_window(self):
        """PRD §3.1: "Assets may be listed and filtered by `home_port_id`, by
        `last_grade_id`, by `status` or by `asset_type`, which is how the operations
        desk finds a compatible barge before scheduling by hand."
        PRD §2.3: "`offset` sets the number of records to skip and defaults to 0;
        negative offsets are not accepted."
        PRD §2.3: "Unless a specific endpoint states otherwise, list results are
        sorted by `created_at` in ascending order."

        `total_count` reports the three barges matching the filter, not the four assets
        registered, and the truck never appears.

        Design: Corner/entities/delivery_asset_listing_filters_and_paginates
        """
        set_logical_clock(CLOCK_EPOCH)
        port = add_port()
        alpha = add_asset(port["id"], name="Bunker Alpha", capacity_mt=3000.000)
        bravo = add_asset(port["id"], name="Bunker Bravo", capacity_mt=2000.000)
        charlie = add_asset(
            port["id"], name="Bunker Charlie", capacity_mt=1500.000,
            boom_certified=False,
        )
        truck = add_asset(
            port["id"], name="Truck One", asset_type="TRUCK", capacity_mt=40.000
        )

        page, meta = validate_paginated(
            api_client.list_delivery_assets(
                OPS,
                params={
                    "home_port_id": port["id"],
                    "asset_type": "BARGE",
                    "limit": 2,
                    "offset": 1,
                },
            )
        )

        assert meta["total_count"] == 3, (
            "Three barges match the filter before paging, got "
            f"{meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "Skipping one of three and taking two exhausts the set"
        )
        assert [row["id"] for row in page] == [bravo["id"], charlie["id"]], (
            f"Expected Bravo then Charlie, got {[row['name'] for row in page]}"
        )
        assert_created_at_ascending(page)
        for row in page:
            assert_delivery_asset(row)
        returned = {row["id"] for row in page}
        assert alpha["id"] not in returned, "The offset must skip the first barge"
        assert truck["id"] not in returned, (
            "The asset_type filter must exclude the truck"
        )


class TestLogicalClock:
    """Every persisted timestamp is drawn from the logical clock."""

    def test_timestamps_follow_the_logical_clock_and_never_the_host(self):
        """PRD §2.4: "Before any clock-setting call has been made, the logical clock
        reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real
        wall-clock time."
        PRD §2.4: "An `OpsCoordinator` may advance or set the clock through an
        administrative test-driving capability that accepts a single instant, supplied
        as `to_iso8601`; the call returns HTTP 200 and no resource payload."
        PRD §2.5: "All resources except index quotes additionally carry `updated_at`,
        an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an
        integer that starts at 1 on creation and increments by one on every mutation of
        the record."

        Moving the clock forward stamps the next row and leaves the earlier row's own
        `created_at` alone.

        Design: Corner/endpoints/clock_endpoint_defaults_and_sets_logical_time
        """
        first = add_port()

        before_move = validate_success(api_client.get_port(first["id"], OPS))
        assert before_move["created_at"].startswith("2026-08-01T00:00:00"), (
            "With no clock call the epoch governs, got "
            f"{before_move['created_at']}"
        )
        assert before_move["updated_at"].startswith("2026-08-01T00:00:00"), (
            f"updated_at opens on the same instant, got {before_move['updated_at']}"
        )

        set_logical_clock(SECOND_CLOCK)
        second = add_port(port_code="SGSIN", name="Singapore", eca_zone=False,
                          notice_lead_hours=12, concurrent_ops_capacity=4)

        assert second["created_at"].startswith("2026-08-05T09:15:00"), (
            "The advanced clock must stamp the new row, got "
            f"{second['created_at']}"
        )
        after_move = validate_success(api_client.get_port(first["id"], OPS))
        assert after_move["created_at"] == before_move["created_at"], (
            "Moving the clock must not rewrite an existing row, got "
            f"{after_move['created_at']}"
        )
