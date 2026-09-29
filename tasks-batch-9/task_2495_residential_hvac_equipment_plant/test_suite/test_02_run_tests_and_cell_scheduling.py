"""Run-test verdicts read from a jointly keyed tolerance table, and the cell
cooldown that decides which windows a cell will accept."""

import pytest

from test_helpers import (
    assert_run_test,
    braze_lot,
    charge_lot,
    create_a1_program,
    create_build_order,
    create_released_high_a2l_platform,
    create_run_test_payload,
    create_test_cell,
    read_build_order,
    record_helium_leak_test,
    setup_charged_high_a2l_lot,
    setup_test_cell_with_one_run_test,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestJointToleranceTable:
    """A HIGH-tier design on a flammable program reads the relaxed cell."""

    def test_run_test_corrects_capacity_to_the_rating_point_and_forms_two_ratios(
        self, api, quality_technician_2_headers
    ):
        """Multiply measured_capacity_btuh by one plus 0.0040 — four tenths of
        one percent per degree — times the number of degrees by which
        measured_ambient_c exceeds 35.0, which is a negative quantity when the
        cell ran cooler than the rating point, and round the product to a whole
        BTU per hour to give corrected_capacity_btuh; capacity_ratio is
        corrected_capacity_btuh divided by the platform's rated_capacity_btuh,
        rounded to four decimal places, and the measured full-load efficiency is
        corrected_capacity_btuh divided by measured_power_w, whose quotient
        divided by the platform's rated_eer and rounded to four decimal places
        gives efficiency_ratio.

        Design: Difficulty/combinatorial_formula/run_test_tolerance_cell_high_a2l_passes_on_relaxed_pair
        """
        scenario = setup_charged_high_a2l_lot(quantity_units=12)
        platform = scenario["platform"]
        assert platform["efficiency_tier"] == "HIGH"
        assert platform["rated_capacity_btuh"] == 36000
        assert float(platform["rated_eer"]) == pytest.approx(12.50, abs=0.001)

        response = api.create_run_test(
            create_run_test_payload(
                scenario["build_order"]["id"],
                scenario["test_cell"]["id"],
                measured_capacity_btuh=35450,
                measured_power_w=2941,
                measured_ambient_c=30.0,
            ),
            quality_technician_2_headers,
        )
        record = validate_success(response, 201)

        assert_run_test(record)
        assert record["corrected_capacity_btuh"] == 34741, (
            "35450 BTU/h measured five degrees below the rating point corrects "
            f"to 34741, got {record['corrected_capacity_btuh']}"
        )
        assert float(record["capacity_ratio"]) == pytest.approx(0.9650, abs=0.00005)
        assert float(record["efficiency_ratio"]) == pytest.approx(0.9450, abs=0.00005)

    def test_high_tier_flammable_pair_admits_ratios_an_a1_cell_would_reject(
        self, api, quality_technician_2_headers
    ):
        """The two tolerances are read from a single cell of a two-dimensional
        table keyed jointly by the platform's efficiency_tier and the program's
        flammability_class. HIGH tier on an A2L program: capacity tolerance
        0.9600, efficiency tolerance 0.9400. The verdict is PASS when
        capacity_ratio is at or above applied_capacity_tolerance and
        efficiency_ratio is at or above applied_efficiency_tolerance, and FAIL
        otherwise.

        Design: Difficulty/combinatorial_formula/run_test_tolerance_cell_high_a2l_passes_on_relaxed_pair
        """
        scenario = setup_charged_high_a2l_lot(quantity_units=12)
        lot_id = scenario["build_order"]["id"]

        record = validate_success(
            api.create_run_test(
                create_run_test_payload(
                    lot_id,
                    scenario["test_cell"]["id"],
                    measured_capacity_btuh=35450,
                    measured_power_w=2941,
                    measured_ambient_c=30.0,
                ),
                quality_technician_2_headers,
            ),
            201,
        )

        assert float(record["applied_capacity_tolerance"]) == pytest.approx(
            0.9600, abs=0.00005
        )
        assert float(record["applied_efficiency_tolerance"]) == pytest.approx(
            0.9400, abs=0.00005
        )
        assert record["verdict"] == "PASS", (
            "0.9650 capacity and 0.9450 efficiency both clear the relaxed pair"
        )

        lot = read_build_order(lot_id)
        assert lot["status"] == "RUN_PASSED"
        assert lot["latest_run_verdict"] == "PASS"
        assert lot["charge_grams"] == 1750, "a passing run keeps the charge in the lot"

        items, meta = validate_paginated(
            api.list_test_cell_run_tests(
                scenario["test_cell"]["id"], quality_technician_2_headers
            )
        )
        assert meta["total_count"] == 1, "the cell holds exactly the one run recorded"
        assert items[0]["verdict"] == "PASS"

    def test_same_measurement_on_a_non_flammable_high_design_fails(
        self, api, quality_technician_2_headers
    ):
        """The table is deliberately not separable into a tier allowance plus a
        class allowance. HIGH tier on an A1 program: capacity tolerance 0.9700,
        efficiency tolerance 0.9500.

        Design: Difficulty/combinatorial_formula/run_test_tolerance_cell_high_a2l_passes_on_relaxed_pair
        """
        program = create_a1_program()
        platform = create_released_high_a2l_platform(
            program["id"], model_code="HX-3600-A1"
        )
        lot = create_build_order(platform["id"], quantity_units=12)
        braze_lot(lot["id"])
        record_helium_leak_test(lot["id"], 1.20)
        charge_lot(lot["id"], 1750)
        cell = create_test_cell("CELL-2")

        record = validate_success(
            api.create_run_test(
                create_run_test_payload(
                    lot["id"],
                    cell["id"],
                    measured_capacity_btuh=35450,
                    measured_power_w=2941,
                    measured_ambient_c=30.0,
                ),
                quality_technician_2_headers,
            ),
            201,
        )

        assert record["corrected_capacity_btuh"] == 34741
        assert float(record["capacity_ratio"]) == pytest.approx(0.9650, abs=0.00005)
        assert float(record["efficiency_ratio"]) == pytest.approx(0.9450, abs=0.00005)
        assert float(record["applied_capacity_tolerance"]) == pytest.approx(
            0.9700, abs=0.00005
        )
        assert float(record["applied_efficiency_tolerance"]) == pytest.approx(
            0.9500, abs=0.00005
        )
        assert record["verdict"] == "FAIL", (
            "the identical ratios miss both non-flammable HIGH tolerances"
        )

        moved = read_build_order(lot["id"])
        assert moved["status"] == "REWORK"
        assert moved["latest_run_verdict"] == "FAIL"
        assert moved["rework_count"] == 1
        assert moved["charge_grams"] == 0, (
            "the refrigerant is recovered from the lot before it is opened"
        )


class TestCellCooldownBuffer:
    """The cooldown is applied on both sides of every occupied window."""

    def test_gap_one_minute_short_of_the_cooldown_is_refused(
        self, api, quality_technician_2_headers
    ):
        """Taking the cell's cooldown_minutes as the buffer, the candidate
        window conflicts with an already-recorded run test on the same cell when
        the candidate's window_start_utc falls strictly before that test's
        window_end_utc advanced by the buffer and that test's window_start_utc
        falls strictly before the candidate's window_end_utc advanced by the
        buffer.

        Design: Difficulty/resource_temporal_overlap/test_cell_refuses_29_minute_gap_and_accepts_exact_cooldown
        """
        scenario = setup_test_cell_with_one_run_test(quantity_units=12)
        cell_id = scenario["test_cell"]["id"]
        assert scenario["test_cell"]["cooldown_minutes"] == 30

        response = api.create_run_test(
            create_run_test_payload(
                scenario["build_order_2"]["id"],
                cell_id,
                window_start_utc="2026-08-05T09:29:00Z",
                window_end_utc="2026-08-05T10:29:00Z",
            ),
            quality_technician_2_headers,
        )
        validate_error(response, "ERR_TEST_CELL_WINDOW_CONFLICT", 409)

        _, meta = validate_paginated(
            api.list_test_cell_run_tests(cell_id, quality_technician_2_headers)
        )
        assert meta["total_count"] == 1, "the refused window left no record behind"
        assert read_build_order(scenario["build_order_2"]["id"])["status"] == "CHARGED"

    def test_gap_of_exactly_the_cooldown_is_accepted(
        self, api, quality_technician_2_headers
    ):
        """Because both comparisons are strict, two windows separated by a gap
        of exactly the cooldown length are accepted while a gap one minute
        shorter is refused; and because windows are half-open, a candidate
        beginning exactly when an existing window ends is still refused unless
        the full cooldown gap is present.

        Design: Difficulty/resource_temporal_overlap/test_cell_refuses_29_minute_gap_and_accepts_exact_cooldown
        """
        scenario = setup_test_cell_with_one_run_test(quantity_units=12)
        cell_id = scenario["test_cell"]["id"]
        second_lot_id = scenario["build_order_2"]["id"]

        record = validate_success(
            api.create_run_test(
                create_run_test_payload(
                    second_lot_id,
                    cell_id,
                    window_start_utc="2026-08-05T09:30:00Z",
                    window_end_utc="2026-08-05T10:30:00Z",
                ),
                quality_technician_2_headers,
            ),
            201,
        )
        assert_run_test(record)
        assert record["corrected_capacity_btuh"] == 35712, (
            "36000 BTU/h measured two degrees below the rating point corrects "
            f"to 35712, got {record['corrected_capacity_btuh']}"
        )
        assert record["verdict"] == "PASS"

        _, meta = validate_paginated(
            api.list_test_cell_run_tests(cell_id, quality_technician_2_headers)
        )
        assert meta["total_count"] == 2, "the cell now holds both runs"
        assert read_build_order(second_lot_id)["status"] == "RUN_PASSED"

    def test_the_refused_window_becomes_legal_one_minute_later(
        self, api, quality_technician_2_headers
    ):
        """The cooldown is a mandatory idle buffer applied on both sides of
        every run-test window that occupies the cell.

        Design: Difficulty/resource_temporal_overlap/test_cell_refuses_29_minute_gap_and_accepts_exact_cooldown
        """
        scenario = setup_test_cell_with_one_run_test(quantity_units=12)
        cell_id = scenario["test_cell"]["id"]
        second_lot_id = scenario["build_order_2"]["id"]

        refused = api.create_run_test(
            create_run_test_payload(
                second_lot_id,
                cell_id,
                window_start_utc="2026-08-05T09:29:00Z",
                window_end_utc="2026-08-05T10:29:00Z",
            ),
            quality_technician_2_headers,
        )
        validate_error(refused, "ERR_TEST_CELL_WINDOW_CONFLICT", 409)

        accepted = validate_success(
            api.create_run_test(
                create_run_test_payload(
                    second_lot_id,
                    cell_id,
                    window_start_utc="2026-08-05T09:30:00Z",
                    window_end_utc="2026-08-05T10:30:00Z",
                ),
                quality_technician_2_headers,
            ),
            201,
        )
        assert accepted["window_start_utc"].startswith("2026-08-05T09:30")

        items, meta = validate_paginated(
            api.list_test_cell_run_tests(cell_id, quality_technician_2_headers)
        )
        assert meta["total_count"] == 2, "only the accepted window was recorded"
        assert all(row["test_cell_id"] == cell_id for row in items)
