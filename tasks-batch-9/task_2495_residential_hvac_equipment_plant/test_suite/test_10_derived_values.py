"""Derived figures: the two leak allowances, the ambient correction, the floored
pool capacity, the open-demand input set, the clipped costing window, and the
effects an allocation already reports in its own response."""

import pytest

from test_helpers import (
    allocate_order,
    allocate_payload,
    assert_effective_units_truncated,
    assert_four_decimals,
    assert_leak_test,
    assert_order_dimensions,
    assert_run_test,
    assert_supply_conservation,
    braze_lot,
    cancel_order_payload,
    charge_lot,
    create_a1_program,
    create_build_order,
    create_run_test_payload,
    create_standard_a1_draft_platform,
    create_test_cell,
    helium_leak_test_payload,
    open_corrective_action_via_third_claim,
    place_order,
    read_build_order,
    read_order,
    read_platform,
    read_reservation,
    read_supply,
    record_helium_leak_test,
    release_platform,
    setup_brazed_standard_a1_lot,
    setup_certified_platform_with_pools,
    setup_platform_two_claims_below_threshold,
    setup_preseason_lot_with_reservation,
    submit_platform,
    validate_paginated,
    validate_success,
)


class TestHeliumAllowanceOnANonFlammableProgram:
    """An A1 lot keeps the whole allowance, and exactly at the limit still passes."""

    def test_measurement_exactly_at_three_grams_passes_on_an_a1_lot(
        self, api, quality_technician_headers, production_planner_headers
    ):
        """The strictness factor is 1.000 for a lot whose platform sits on an A1
        program, and exactly one half — 0.500 — for a lot whose platform sits on an
        A2L program, because a flammable charge must not leak. Under
        HELIUM_MASS_SPEC, the applied_limit is the plant's base helium allowance of
        3.000 grams per year multiplied by that strictness factor and rounded to
        three decimal places; the verdict is PASS when
        measured_leak_rate_g_per_year is at or below applied_limit and FAIL
        otherwise.

        Design: Corner/calculations/c_leak_limit_for_a1_class_uses_full_helium_allowance
        """
        scenario = setup_brazed_standard_a1_lot(quantity_units=10)
        lot_id = scenario["build_order"]["id"]

        record = validate_success(
            api.create_leak_test(
                helium_leak_test_payload(lot_id, measured_leak_rate_g_per_year=3.00),
                quality_technician_headers,
            ),
            201,
        )

        assert_leak_test(record)
        assert float(record["applied_limit"]) == pytest.approx(3.000, abs=0.0005), (
            "an A1 lot is not tightened, so the whole allowance applies"
        )
        assert record["verdict"] == "PASS", "the comparison is at or below the limit"
        assert record["method"] == "HELIUM_MASS_SPEC"
        assert record["decay_kpa"] is None

        lot = read_build_order(lot_id)
        assert lot["status"] == "LEAK_PASSED"
        assert lot["latest_leak_verdict"] == "PASS"
        assert lot["rework_count"] == 0

        _, meta = validate_paginated(
            api.list_build_order_leak_tests(lot_id, production_planner_headers)
        )
        assert meta["total_count"] == 1


class TestAmbientCorrectionAboveTheRatingPoint:
    """A hot cell raises the corrected capacity instead of lowering it."""

    def test_forty_degree_cell_lifts_thirty_five_thousand_to_thirty_five_seven_hundred(
        self, api, quality_technician_2_headers, production_planner_headers
    ):
        """First, the measurement is corrected to the plant's 35.0-degree-Celsius
        rating point: multiply measured_capacity_btuh by one plus 0.0040 — four
        tenths of one percent per degree — times the number of degrees by which
        measured_ambient_c exceeds 35.0, which is a negative quantity when the cell
        ran cooler than the rating point, and round the product to a whole BTU per
        hour to give corrected_capacity_btuh. HIGH tier on an A1 program: capacity
        tolerance 0.9700, efficiency tolerance 0.9500.

        Design: Corner/calculations/c_run_test_ambient_above_rating_point_raises_corrected_capacity
        """
        program = create_a1_program()
        draft = create_standard_a1_draft_platform(
            program["id"],
            model_code="LX-3600-A1",
            efficiency_tier="HIGH",
            rated_capacity_btuh=36000,
            rated_eer=12.50,
            rated_seer2=15.40,
            compressor_part_number="CMP-5T-A1",
            control_board_part_number="CTL-9X",
        )
        submit_platform(draft["id"])
        platform = release_platform(draft["id"])
        cell = create_test_cell("CELL-1")
        lot = create_build_order(
            platform["id"], quantity_units=10, scheduled_start_utc="2026-08-05T06:00:00Z"
        )
        braze_lot(lot["id"])
        record_helium_leak_test(lot["id"], 2.40)
        charge_lot(lot["id"], 2100)

        run_test = validate_success(
            api.create_run_test(
                create_run_test_payload(
                    lot["id"],
                    cell["id"],
                    window_start_utc="2026-08-05T08:00:00Z",
                    window_end_utc="2026-08-05T09:00:00Z",
                    measured_capacity_btuh=35000,
                    measured_power_w=2900,
                    measured_ambient_c=40.0,
                ),
                quality_technician_2_headers,
            ),
            201,
        )

        assert_run_test(run_test)
        assert run_test["corrected_capacity_btuh"] == 35700, (
            "five degrees above the rating point multiplies by 1.02, got "
            f"{run_test['corrected_capacity_btuh']}"
        )
        assert_four_decimals(run_test["capacity_ratio"], "capacity_ratio")
        assert_four_decimals(run_test["efficiency_ratio"], "efficiency_ratio")
        assert float(run_test["capacity_ratio"]) == pytest.approx(0.9917, abs=0.00005)
        assert float(run_test["efficiency_ratio"]) == pytest.approx(0.9848, abs=0.00005)
        assert float(run_test["applied_capacity_tolerance"]) == pytest.approx(
            0.9700, abs=0.00005
        )
        assert float(run_test["applied_efficiency_tolerance"]) == pytest.approx(
            0.9500, abs=0.00005
        )
        assert run_test["verdict"] == "PASS"
        assert read_build_order(lot["id"])["status"] == "RUN_PASSED"

        records, meta = validate_paginated(
            api.list_build_order_run_tests(lot["id"], production_planner_headers)
        )
        assert meta["total_count"] == 1
        assert records[0]["id"] == run_test["id"]


class TestEffectiveCapacityFloorsAFraction:
    """Three quarters of a compressor is not allocatable, so the figure floors."""

    def test_quarter_cut_of_one_hundred_one_units_stores_seventy_five(self, api):
        """effective_allocatable_units is total_allocatable_units reduced by the
        current cut: take the percentage that survives, which is 100 minus
        derate_pct, multiply the committed total by it, divide by 100, and truncate
        downward to a whole unit — a 25 percent cut of 101 units therefore leaves
        75, not 75.75. available_units is effective_allocatable_units less
        reserved_units less committed_units, and the conserved identity of §2.9
        must hold after every allocation, revocation, release, cancellation,
        shipment, derate, and derate restoration.

        Design: Corner/calculations/c_supply_effective_capacity_floors_odd_unit_count
        """
        scenario = setup_platform_two_claims_below_threshold(
            quantity_units=60, compressor_units=101
        )
        assert scenario["platform"]["warranty_posture"] == "OK", (
            "two claims are below the posture gate"
        )

        open_corrective_action_via_third_claim(scenario["platform"]["id"], 40200)

        platform = read_platform(scenario["platform"]["id"])
        assert float(platform["rolling_claim_rate_pct"]) == pytest.approx(
            5.00, abs=0.005
        )
        assert platform["warranty_posture"] == "CAPA_REQUIRED"

        pool = read_supply(scenario["compressor"]["id"])
        assert pool["derate_pct"] == 25
        assert pool["effective_allocatable_units"] == 75, (
            "75.75 units of capacity truncate down to 75, got "
            f"{pool['effective_allocatable_units']}"
        )
        assert pool["available_units"] == 75
        assert pool["reserved_units"] == 0
        assert pool["committed_units"] == 0
        assert pool["total_allocatable_units"] == 101, (
            "the cut is a view on capacity, not a rewrite of the purchase"
        )
        assert_effective_units_truncated(pool)
        assert_supply_conservation(pool)


class TestOpenDemandInputSet:
    """A fully allocated order and a cancelled order both leave the demand sum."""

    def test_only_the_surviving_order_counts_toward_total_open_demand(
        self, api, supply_planner_headers, distributor_rep_2_headers
    ):
        """total_open_demand is the sum, over every distributor order for the same
        platform_id and the same requested_delivery_month whose fulfillment_status
        is PENDING and whose allocation_status is not FULLY_ALLOCATED, of that
        order's requested_units less its allocated_units — and the order being
        allocated is itself included in that sum. Under DEMAND_PRORATA, a fair
        share is computed first by multiplying kit_capacity by remaining_need,
        dividing by total_open_demand, and truncating downward to a whole unit;
        granted_units is then the smaller of remaining_need and that fair share.

        Design: Corner/calculations/c_total_open_demand_excludes_cancelled_and_fully_allocated_orders
        """
        scenario = setup_certified_platform_with_pools(
            compressor_units=100, board_units=100
        )
        platform_id = scenario["platform"]["id"]
        order_a = place_order(
            platform_id,
            requested_units=40,
            priority_score=90,
            distributor_code="DIST-A",
            rep_id="user-dr-1",
        )
        order_b = place_order(
            platform_id,
            requested_units=30,
            priority_score=80,
            distributor_code="DIST-B",
            rep_id="user-dr-2",
        )
        order_c = place_order(
            platform_id,
            requested_units=50,
            priority_score=50,
            distributor_code="DIST-C",
            rep_id="user-dr-3",
        )
        allocate_order(order_a["id"], scenario["compressor"]["id"])
        validate_success(
            api.cancel_distributor_order(
                order_b["id"],
                cancel_order_payload("Distributor consolidated its pre-season buy"),
                distributor_rep_2_headers,
            )
        )

        preview = validate_success(
            api.get_allocation_preview(
                order_c["id"],
                supply_planner_headers,
                params={"policy": "DEMAND_PRORATA"},
            )
        )

        assert preview["total_open_demand"] == 50, (
            "the allocated order and the cancelled order are both out of the sum, "
            f"got {preview['total_open_demand']}"
        )
        assert preview["compressor_pool"] == 60
        assert preview["board_pool"] == 60
        assert preview["kit_capacity"] == 60
        assert preview["remaining_need"] == 50
        assert preview["granted_units"] == 50, "the fair share is capped by the need"

        stored_a = read_order(order_a["id"])
        assert_order_dimensions(stored_a, "FULLY_ALLOCATED", "PENDING")
        assert stored_a["allocated_units"] == 40

        stored_b = read_order(order_b["id"])
        assert_order_dimensions(stored_b, "UNALLOCATED", "CANCELLED")
        assert stored_b["allocated_units"] == 0


class TestCarryingCostWindowClipping:
    """A reservation straddling both ends is billed for the intersection only."""

    def test_twenty_day_reservation_is_billed_for_the_ten_queried_days(
        self, api, production_planner_headers
    ):
        """For each such reservation, its occupied days are the number of whole
        days in the intersection of its own half-open interval with the requested
        half-open window. The pallet_week_total is then the sum, across those
        reservations, of the reservation's pallet_units multiplied by its occupied
        days and divided by seven, rounded to four decimal places; that figure is
        reported identically under both bases.

        Design: Corner/calculations/c_carrying_cost_clips_reservation_to_requested_window
        """
        scenario = setup_preseason_lot_with_reservation(
            pallet_capacity=50,
            quantity_units=12,
            pallet_units=6,
            scheduled_start_utc="2026-11-02T06:00:00Z",
            start_date="2026-11-02",
            end_date="2026-11-22",
        )

        cost = validate_success(
            api.get_warehouse_carrying_cost(
                scenario["warehouse"]["id"],
                production_planner_headers,
                params={"window_start": "2026-11-10", "window_end": "2026-11-20"},
            )
        )

        assert cost["reservation_count"] == 1
        assert_four_decimals(cost["pallet_week_total"], "pallet_week_total")
        assert float(cost["pallet_week_total"]) == pytest.approx(8.5714, abs=0.00005), (
            "six pallets over the ten clipped days is 60 pallet-days over seven"
        )
        assert cost["carrying_cost_cents"] == 9986, (
            "only the intersection is billed, got "
            f"{cost['carrying_cost_cents']}"
        )

        assert read_reservation(scenario["reservation"]["id"])["status"] == "ACTIVE", (
            "a costing read mutates nothing"
        )


class TestAllocationEffectsAreImmediatelyReadable:
    """The draw is complete when the response returns, with no settling period."""

    def test_the_allocate_response_and_the_reads_that_follow_agree(
        self, api, supply_planner_headers
    ):
        """The order recomputes allocated_units — defined as the summed units of
        its allocation lines whose component_type is COMPRESSOR and whose status is
        RESERVED or COMMITTED, so that a kit is counted once and not twice — and
        its version is incremented. Each drawn pool then recomputes reserved_units
        and available_units, may move ACTIVE to EXHAUSTED, and has its version
        incremented.

        Design: Corner/consistency_model/c_allocation_effects_are_visible_in_the_same_response
        """
        scenario = setup_certified_platform_with_pools(
            compressor_units=50, board_units=50
        )
        compressor_id = scenario["compressor"]["id"]
        order = place_order(
            scenario["platform"]["id"], requested_units=30, priority_score=70
        )
        pool_version = read_supply(compressor_id)["version"]
        assert pool_version == 1

        allocated = validate_success(
            api.allocate_distributor_order(
                order["id"], allocate_payload(pool_version), supply_planner_headers
            )
        )
        assert_order_dimensions(allocated, "FULLY_ALLOCATED", "PENDING")
        assert allocated["allocated_units"] == 30, (
            "the mutating response already carries the new figure"
        )

        pool = validate_success(
            api.get_component_supply(compressor_id, supply_planner_headers)
        )
        assert pool["reserved_units"] == 30
        assert pool["available_units"] == 20
        assert pool["version"] == 2
        assert_supply_conservation(pool)

        lines, lines_meta = validate_paginated(
            api.list_order_allocation_lines(order["id"], supply_planner_headers)
        )
        assert lines_meta["total_count"] == 2
        for line in lines:
            assert line["status"] == "RESERVED"
            assert line["units"] == 30

        stored_order = read_order(order["id"])
        assert stored_order["allocation_status"] == allocated["allocation_status"]
        assert stored_order["allocated_units"] == allocated["allocated_units"]
