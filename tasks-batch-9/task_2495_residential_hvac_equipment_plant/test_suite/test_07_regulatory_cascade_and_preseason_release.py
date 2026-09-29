"""The sell-through cascade reaching all the way to pallet occupancy, and the
pre-season release that depends on space it no longer holds."""

from test_helpers import (
    assert_instant_equals,
    assert_warehouse_pallet_identity,
    create_build_order_payload,
    create_warehouse_reservation_payload,
    read_build_order,
    read_platform,
    read_reservation,
    read_warehouse,
    setup_preseason_lot_with_released_reservation,
    setup_sell_through_cascade_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSellThroughCascade:
    """One admin transition, four caused hops."""

    def test_entering_sell_through_restricts_the_released_platform(
        self, api, plant_admin_headers
    ):
        """On success the program's status becomes SELL_THROUGH,
        sell_through_entered_at is stamped with the logical clock, and the
        program's version increases by one. From that point on, opening a new
        build lot against that platform is refused with
        ERR_INVALID_PLATFORM_STATE, while stock that is already finished may still
        ship until the sell-through deadline arrives.

        Design: Difficulty/transitive_cascade/sell_through_cascade_frees_warehouse_pallets_in_four_hops
        """
        scenario = setup_sell_through_cascade_scenario()
        assert scenario["platform"]["status"] == "RELEASED"

        program = validate_success(
            api.enter_sell_through(scenario["program"]["id"], plant_admin_headers)
        )
        assert program["status"] == "SELL_THROUGH"
        assert_instant_equals(
            program["sell_through_entered_at"],
            "2026-10-02T00:00:00Z",
            "sell_through_entered_at",
        )
        assert program["version"] == scenario["program"]["version"] + 1

        platform = read_platform(scenario["platform"]["id"])
        assert platform["status"] == "RESTRICTED"
        assert platform["blocked_region_codes"] == [], (
            "no standard participates, so no region qualifies as blocked"
        )
        assert platform["salable_region_count"] == 0

    def test_the_hold_reaches_the_lot_and_then_its_reservation(
        self, api, plant_admin_headers
    ):
        """Entering the sell-through window on a refrigerant program restricts
        its released platforms; each restriction places that platform's open build
        lots on regulatory hold; each hold releases those lots' active warehouse
        reservations; each release recomputes the holding warehouse's pallet
        occupancy.

        Design: Difficulty/transitive_cascade/sell_through_cascade_frees_warehouse_pallets_in_four_hops
        """
        scenario = setup_sell_through_cascade_scenario()
        assert scenario["build_order"]["status"] == "DRAFT"
        assert scenario["reservation"]["status"] == "ACTIVE"

        validate_success(
            api.enter_sell_through(scenario["program"]["id"], plant_admin_headers)
        )

        lot = read_build_order(scenario["build_order"]["id"])
        assert lot["status"] == "HOLD_REGULATORY"
        assert lot["hold_reason"] == "REFRIGERANT_SELL_THROUGH"

        reservation = read_reservation(scenario["reservation"]["id"])
        assert reservation["status"] == "RELEASED"
        assert reservation["release_reason"] == "BUILD_ON_REGULATORY_HOLD"
        assert_instant_equals(
            reservation["released_at"], "2026-10-02T00:00:00Z", "released_at"
        )

    def test_the_freed_pallets_leave_the_warehouse_occupancy(
        self, api, plant_admin_headers, production_planner_headers
    ):
        """Those reaches are transitive: each hop is caused by the mutation the
        previous hop performed, not by the original request. For a warehouse,
        pallets_reserved_current equals the summed pallet_units of the active
        reservations covering the logical clock's date.

        Design: Difficulty/transitive_cascade/sell_through_cascade_frees_warehouse_pallets_in_four_hops
        """
        scenario = setup_sell_through_cascade_scenario()
        warehouse_id = scenario["warehouse"]["id"]
        assert read_warehouse(warehouse_id)["pallets_reserved_current"] == 20

        validate_success(
            api.enter_sell_through(scenario["program"]["id"], plant_admin_headers)
        )

        warehouse = read_warehouse(warehouse_id)
        assert warehouse["pallets_reserved_current"] == 0
        assert_warehouse_pallet_identity(warehouse, [])

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-10-02"}
            )
        )
        assert occupancy["occupancy_units"] == 0, (
            "released reservations are excluded from every day"
        )

        refused = api.create_build_order(
            create_build_order_payload(scenario["platform"]["id"], quantity_units=6),
            production_planner_headers,
        )
        validate_error(refused, "ERR_INVALID_PLATFORM_STATE", 409)


class TestPreseasonReleaseNeedsLiveSpace:
    """A pre-season lot may not close without pallet space on the clock's date."""

    def test_release_to_stock_is_refused_once_the_space_is_gone(
        self, api, production_planner_headers
    ):
        """A pre-season lot carries one extra condition: at least one warehouse
        reservation of that lot must have status ACTIVE and must cover the logical
        clock's date, meaning its start_date is at or before that date and its
        end_date strictly after it; otherwise the release is refused with
        ERR_NO_WAREHOUSE_RESERVATION.

        Design: Difficulty/cross_entity_state_dependency/preseason_release_to_stock_refused_after_reservation_released
        """
        scenario = setup_preseason_lot_with_released_reservation()
        lot_id = scenario["build_order"]["id"]
        assert scenario["build_order"]["status"] == "RUN_PASSED"
        assert scenario["build_order"]["is_preseason"] is True
        assert scenario["reservation"]["status"] == "RELEASED"

        response = api.release_to_stock(lot_id, production_planner_headers)
        validate_error(response, "ERR_NO_WAREHOUSE_RESERVATION", 409)

        lot = read_build_order(lot_id)
        assert lot["status"] == "RUN_PASSED"
        assert lot["released_to_stock_at"] is None
        assert read_platform(scenario["platform"]["id"])["units_built_released"] == 0

    def test_the_run_passed_lot_cannot_book_replacement_space(
        self, api, production_planner_headers
    ):
        """Only a pre-season lot may hold pallet space, and only while it is
        still in production. A reservation is refused with
        ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD when the named lot's is_preseason is
        false, or when its status is any of LEAK_PASSED, CHARGED, RUN_PASSED,
        RELEASED_TO_STOCK, SCRAPPED, CANCELLED, or HOLD_REGULATORY — which leaves
        DRAFT, COIL_FAB, BRAZED, and REWORK as the four stages at which space may
        be booked.

        Design: Difficulty/cross_entity_state_dependency/preseason_release_to_stock_refused_after_reservation_released
        """
        scenario = setup_preseason_lot_with_released_reservation()
        lot_id = scenario["build_order"]["id"]
        warehouse_id = scenario["warehouse"]["id"]

        rebooking = api.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                warehouse_id,
                lot_id,
                start_date="2026-08-01",
                end_date="2026-09-01",
                pallet_units=10,
            ),
            production_planner_headers,
        )
        validate_error(rebooking, "ERR_RESERVATION_NOT_ALLOWED_FOR_BUILD", 409)

        _, active_meta = validate_paginated(
            api.list_build_order_warehouse_reservations(
                lot_id, production_planner_headers, params={"status": "ACTIVE"}
            )
        )
        assert active_meta["total_count"] == 0, "the lot holds no live pallet space"

        still_refused = api.release_to_stock(lot_id, production_planner_headers)
        validate_error(still_refused, "ERR_NO_WAREHOUSE_RESERVATION", 409)
        assert read_warehouse(warehouse_id)["pallets_reserved_current"] == 0
