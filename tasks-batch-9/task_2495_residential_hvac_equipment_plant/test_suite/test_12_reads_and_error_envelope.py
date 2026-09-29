"""Reads and refusals: the lot listing under a filter and a page, the clock's
grip on every stamp, the two partitions of one allocation, an undeclared role, an
unknown warehouse, a live certification that will not be superseded, and a draw
with no pool for the month asked for."""

import pytest

from test_helpers import (
    UNKNOWN_ID,
    allocate_payload,
    assert_allocation_line,
    assert_certification_record,
    assert_instant_equals,
    assert_order_dimensions,
    assert_supply_conservation,
    assert_warehouse,
    braze_lot,
    certify_certification,
    create_a1_program,
    create_build_order,
    create_certification_record_payload,
    create_compressor_supply,
    create_control_board_supply,
    create_released_standard_a1_platform,
    create_southeast_standard,
    create_warehouse,
    file_certification,
    make_headers,
    place_order,
    read_build_order,
    read_order,
    read_platform,
    read_supply,
    set_clock,
    setup_allocated_order,
    setup_certified_high_a2l_platform,
    submit_certification,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBuildOrderListing:
    """Three lots at three stages: the filter counts one, the page counts three."""

    def test_status_filter_reports_one_row_while_the_limited_page_reports_three(
        self, api, production_planner_headers, production_technician_headers
    ):
        """List endpoints accept two query parameters. limit caps the number of rows
        returned; when it is omitted it defaults to 10, and the accepted range is a
        minimum of 1 and a maximum of 100. Every list response carries limit,
        offset, total_count, and has_more inside the meta object of the envelope
        described in §2.2. Lots are listable and filterable by platform_id, by
        status, and by is_preseason.

        Design: Corner/endpoints/c_list_build_orders_filters_by_status_and_paginates
        """
        program = create_a1_program(
            manufacture_cutoff_utc="2027-01-01T00:00:00Z",
            sell_through_deadline_utc="2027-07-01T00:00:00Z",
        )
        platform = create_released_standard_a1_platform(program["id"])
        first = create_build_order(
            platform["id"], quantity_units=10, scheduled_start_utc="2026-08-05T06:00:00Z"
        )
        second = create_build_order(
            platform["id"], quantity_units=12, scheduled_start_utc="2026-08-06T06:00:00Z"
        )
        third = create_build_order(
            platform["id"], quantity_units=14, scheduled_start_utc="2026-08-07T06:00:00Z"
        )
        validate_success(
            api.start_coil_fab(second["id"], production_technician_headers)
        )
        braze_lot(third["id"])

        brazed, brazed_meta = validate_paginated(
            api.list_build_orders(production_planner_headers, params={"status": "BRAZED"})
        )
        assert brazed_meta["total_count"] == 1
        assert brazed_meta["has_more"] is False
        assert len(brazed) == 1
        assert brazed[0]["id"] == third["id"]

        page, page_meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers, params={"limit": 2, "offset": 0}
            )
        )
        assert len(page) == 2
        assert page_meta["total_count"] == 3, (
            "the unfiltered count sees every lot, got "
            f"{page_meta['total_count']}"
        )
        assert page_meta["has_more"] is True
        assert page_meta["limit"] == 2
        assert page_meta["offset"] == 0

        _, preseason_meta = validate_paginated(
            api.list_build_orders(
                production_planner_headers, params={"is_preseason": "true"}
            )
        )
        assert preseason_meta["total_count"] == 0, (
            "all three lots took the default flag"
        )

        assert read_build_order(first["id"])["status"] == "DRAFT"
        assert read_build_order(second["id"])["status"] == "COIL_FAB"
        assert read_build_order(third["id"])["status"] == "BRAZED"


class TestClockControlsEveryStamp:
    """The row written before the clock moves keeps the default instant."""

    def test_two_warehouses_are_stamped_from_the_clock_that_was_current(
        self, api, production_planner_headers
    ):
        """Nothing in this system reads wall-clock time. Before any client sets it,
        the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls
        back to real time. Most rows additionally expose updated_at, an ISO 8601 UTC
        timestamp refreshed on every mutation, and version, an integer that begins
        at 1 when the row is created and increases by exactly 1 on every mutation of
        that row.

        Design: Corner/endpoints/c_clock_set_endpoint_moves_stamp_for_subsequent_writes
        """
        before = create_warehouse("WH-BEFORE", 40)
        assert_warehouse(before)
        assert_instant_equals(
            before["created_at"], "2026-08-01T00:00:00Z", "created_at"
        )

        set_clock("2026-12-24T09:15:00Z")
        after = create_warehouse("WH-AFTER", 40)

        assert_instant_equals(
            after["created_at"], "2026-12-24T09:15:00Z", "created_at"
        )

        stored_before = validate_success(
            api.get_warehouse(before["id"], production_planner_headers)
        )
        assert_instant_equals(
            stored_before["updated_at"], "2026-08-01T00:00:00Z", "updated_at"
        )
        assert stored_before["version"] == 1, "moving the clock is not a mutation"
        assert stored_before["pallets_reserved_current"] == 0
        assert after["pallets_reserved_current"] == 0


class TestAllocationLineReadPaths:
    """One draw, two lines, and two reads that partition them differently."""

    def test_the_pool_shows_its_own_line_while_the_order_shows_both(
        self, api, supply_planner_headers
    ):
        """Lines are listable in their own right, filterable by
        distributor_order_id, by component_supply_id, by component_type, and by
        status, and also readable as sub-collections of a pool or of an order.
        Because one finished unit consumes exactly one compressor and exactly one
        control board, kit_capacity is the smaller of compressor_pool and
        board_pool.

        Design: Corner/endpoints/c_component_supply_allocation_lines_sub_resource_lists_lines
        """
        scenario = setup_allocated_order(
            requested_units=40, compressor_units=60, board_units=60
        )
        order_id = scenario["order"]["id"]
        compressor_id = scenario["compressor"]["id"]
        board_id = scenario["control_board"]["id"]
        version_before = read_supply(compressor_id)["version"]

        own_lines, own_meta = validate_paginated(
            api.list_supply_allocation_lines(compressor_id, supply_planner_headers)
        )
        assert own_meta["total_count"] == 1, "the pool sees only what was drawn from it"
        assert len(own_lines) == 1
        line = own_lines[0]
        assert_allocation_line(line)
        assert line["component_type"] == "COMPRESSOR"
        assert line["units"] == 40
        assert line["status"] == "RESERVED"
        assert line["component_supply_id"] == compressor_id
        assert line["distributor_order_id"] == order_id

        both_lines, both_meta = validate_paginated(
            api.list_allocation_lines(
                supply_planner_headers, params={"distributor_order_id": order_id}
            )
        )
        assert both_meta["total_count"] == 2
        assert sorted(row["component_type"] for row in both_lines) == [
            "COMPRESSOR",
            "CONTROL_BOARD",
        ], "the kit is two lines, one per component type"
        for row in both_lines:
            assert row["status"] == "RESERVED"
            assert row["units"] == 40

        compressor = read_supply(compressor_id)
        assert compressor["reserved_units"] == 40
        assert compressor["available_units"] == 20
        assert compressor["version"] == version_before, "a read is not a mutation"
        assert_supply_conservation(compressor)

        board = read_supply(board_id)
        assert board["reserved_units"] == 40
        assert board["available_units"] == 20
        assert_supply_conservation(board)


class TestUndeclaredRoleHeader:
    """A role outside the eleven is refused exactly like a forbidden one."""

    def test_a_role_string_that_is_not_recognized_leaks_no_listing(
        self, api, plant_admin_headers
    ):
        """If X-User-Role is absent, is not one of those eleven strings, or is not
        among the roles authorized for the requested operation, the request is
        rejected with ERR_UNAUTHORIZED (403 Forbidden). This authorization check is
        the very first gate applied to any request: an unauthorized caller who also
        sends a malformed body receives ERR_UNAUTHORIZED, never a schema complaint.

        Design: Corner/errors/c_unknown_role_header_returns_unauthorized
        """
        create_a1_program()

        response = api.list_product_platforms(
            make_headers("user-pa-1", "PlantJanitor")
        )
        validate_error(response, "ERR_UNAUTHORIZED", 403)

        body = response.json()
        assert body["response_type"] == "error"
        assert "total_count" not in body["data"], "no partial listing leaks"

        _, meta = validate_paginated(api.list_product_platforms(plant_admin_headers))
        assert meta["total_count"] == 0, "a permitted role reads the same empty table"


class TestUnknownWarehouseOccupancy:
    """Resolution precedes computation even on a computed sub-resource."""

    def test_occupancy_of_an_unknown_warehouse_is_a_not_found_not_a_zero_report(
        self, api, production_planner_headers
    ):
        """Referential integrity and uniqueness. Applying to every endpoint that
        carries an identifier: unresolvable path identifiers and unresolvable
        payload foreign keys yield the appropriate not-found error from the family
        listed in §2.7. The occupancy of a warehouse on day D is the summed
        pallet_units of that warehouse's reservations whose status is ACTIVE and
        which occupy D; released reservations are excluded from every day, including
        days already elapsed.

        Design: Corner/errors/c_unknown_warehouse_id_occupancy_not_found
        """
        set_clock("2026-11-05T00:00:00Z")
        warehouse = create_warehouse("WH-1", 50)

        response = api.get_warehouse_occupancy(
            UNKNOWN_ID, production_planner_headers, params={"on_date": "2026-11-05"}
        )
        validate_error(response, "ERR_WAREHOUSE_NOT_FOUND", 404)

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse["id"],
                production_planner_headers,
                params={"on_date": "2026-11-05"},
            )
        )
        assert occupancy["occupancy_units"] == 0, "the real warehouse is unaffected"


class TestCertifiedFilingIsNotSuperseded:
    """Supersession stops short of a live certification."""

    def test_a_second_southeast_filing_over_a_certified_one_is_refused(
        self, api, certification_engineer_headers, plant_admin_headers
    ):
        """The platform must resolve, otherwise ERR_PLATFORM_NOT_FOUND; the
        stale-version guard fires next as ERR_STALE_PLATFORM_VERSION; the platform's
        status must then be RELEASED or RESTRICTED, otherwise
        ERR_INVALID_PLATFORM_STATE; and no existing record for the same platform_id
        and region_code may already hold status CERTIFIED, otherwise
        ERR_DUPLICATE_CERTIFICATION. Every earlier record for the same
        platform-and-region pair whose status is DRAFT, SUBMITTED, or REJECTED is
        driven DRAFT to SUPERSEDED (or from SUBMITTED or REJECTED to SUPERSEDED),
        processed oldest first, each one's version increasing by one.

        Design: Corner/errors/c_duplicate_active_certification_rejected
        """
        standard = create_southeast_standard()
        program = create_a1_program()
        platform = create_released_standard_a1_platform(program["id"])
        record = file_certification(
            platform["id"],
            platform["version"],
            region_code="SOUTHEAST",
            rated_seer2_submitted=14.60,
        )
        submit_certification(record["id"])
        certified = certify_certification(record["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["governing_standard_id"] == standard["id"]
        current_version = read_platform(platform["id"])["version"]

        response = api.create_certification_record(
            create_certification_record_payload(
                platform["id"],
                current_version,
                region_code="SOUTHEAST",
                rated_seer2_submitted=14.90,
            ),
            make_headers("user-ce-2", "CertificationEngineer"),
        )
        validate_error(response, "ERR_DUPLICATE_CERTIFICATION", 409)

        records, meta = validate_paginated(
            api.list_certification_records(
                plant_admin_headers, params={"platform_id": platform["id"]}
            )
        )
        assert meta["total_count"] == 1, "the refused filing opened no record"
        assert records[0]["id"] == record["id"]

        stored = validate_success(
            api.get_certification_record(record["id"], certification_engineer_headers)
        )
        assert_certification_record(stored)
        assert stored["status"] == "CERTIFIED"
        assert float(stored["rated_seer2_submitted"]) == pytest.approx(
            14.60, abs=0.005
        )

        stored_platform = read_platform(platform["id"])
        assert stored_platform["blocked_region_codes"] == []
        assert stored_platform["salable_region_count"] == 1


class TestEligibilityMatchesPartNumberAndMonth:
    """A December pool cannot serve a November order at any price."""

    def test_a_draw_with_no_pool_for_the_requested_month_is_refused(
        self, api, supply_planner_headers
    ):
        """The eligible compressor pools are those component supplies whose
        component_type is COMPRESSOR, whose part_number equals the platform's
        compressor_part_number, whose supply_month equals the order's
        requested_delivery_month, whose status is ACTIVE or DERATED, and whose
        available_units is at least 1. And the plan must actually yield something: a
        computed grant below one unit is refused with ERR_NO_ELIGIBLE_SUPPLY.

        Design: Corner/errors/c_allocate_with_no_eligible_supply_month_returns_error
        """
        scenario = setup_certified_high_a2l_platform()
        platform = scenario["platform"]
        december = create_compressor_supply(
            part_number=platform["compressor_part_number"],
            supplier_lot_code="LOT-CMP-DEC",
            supply_month="2026-12",
            total_allocatable_units=80,
        )
        november_boards = create_control_board_supply(
            part_number=platform["control_board_part_number"],
            supply_month="2026-11",
            total_allocatable_units=80,
        )
        order = place_order(
            platform["id"], requested_units=30, requested_delivery_month="2026-11"
        )

        response = api.allocate_distributor_order(
            order["id"],
            allocate_payload(december["version"]),
            supply_planner_headers,
        )
        validate_error(response, "ERR_NO_ELIGIBLE_SUPPLY", 409)

        stored_order = read_order(order["id"])
        assert_order_dimensions(stored_order, "UNALLOCATED", "PENDING")
        assert stored_order["allocated_units"] == 0

        stored_december = read_supply(december["id"])
        assert stored_december["reserved_units"] == 0
        assert stored_december["available_units"] == 80
        assert stored_december["version"] == december["version"], (
            "the refused draw advanced no token"
        )

        stored_boards = read_supply(november_boards["id"])
        assert stored_boards["reserved_units"] == 0
        assert stored_boards["available_units"] == 80, (
            "the board pool was not drawn against on its own"
        )

        _, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order["id"], supply_planner_headers)
        )
        assert lines_meta["total_count"] == 0
