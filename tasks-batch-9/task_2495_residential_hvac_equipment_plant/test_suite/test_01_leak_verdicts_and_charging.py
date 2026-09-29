"""Sealing a brazed lot: the two leak-test variants, the repair budget, and the
order in which the charging gates fire."""

import pytest

from test_helpers import (
    assert_build_order,
    assert_instant_equals,
    assert_leak_test,
    charge_payload,
    helium_leak_test_payload,
    pressure_decay_leak_test_payload,
    read_build_order,
    setup_brazed_high_a2l_lot,
    setup_lot_after_two_failed_leak_cycles,
    setup_two_brazed_high_a2l_lots,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLeakVerdictByMethod:
    """The same measured magnitude is judged against two different limits."""

    def test_pressure_decay_of_1_90_kpa_over_a_30_minute_hold_passes_a_flammable_lot(
        self, api, quality_technician_headers
    ):
        """Under PRESSURE_DECAY, the applied_limit is the plant's allowance of
        2.00 kilopascals for every 15 minutes of hold — that is, 2.00 multiplied
        by hold_minutes divided by 15 — multiplied by the strictness factor and
        rounded to two decimal places; the verdict is PASS when decay_kpa is at
        or below applied_limit and FAIL otherwise.

        Design: Difficulty/dual_variant_calc/leak_verdict_diverges_by_method_on_same_magnitude
        """
        scenario = setup_two_brazed_high_a2l_lots(quantity_units=12)
        lot_id = scenario["build_order_1"]["id"]

        response = api.create_leak_test(
            pressure_decay_leak_test_payload(lot_id, decay_kpa=1.90, hold_minutes=30),
            quality_technician_headers,
        )
        record = validate_success(response, 201)

        assert_leak_test(record)
        assert record["method"] == "PRESSURE_DECAY"
        assert float(record["applied_limit"]) == pytest.approx(2.00, abs=0.001), (
            f"a 30-minute hold on an A2L lot allows 2.00 kPa, got {record['applied_limit']}"
        )
        assert record["verdict"] == "PASS", "1.90 kPa is at or below the 2.00 kPa limit"

        lot = read_build_order(lot_id)
        assert_build_order(lot)
        assert lot["status"] == "LEAK_PASSED"
        assert lot["latest_leak_verdict"] == "PASS"
        assert lot["rework_count"] == 0, "a passing lot spends none of its repair budget"

    def test_helium_leak_rate_of_1_90_grams_per_year_fails_a_flammable_lot(
        self, api, quality_technician_headers
    ):
        """Under HELIUM_MASS_SPEC, the applied_limit is the plant's base helium
        allowance of 3.000 grams per year multiplied by that strictness factor
        and rounded to three decimal places; the verdict is PASS when
        measured_leak_rate_g_per_year is at or below applied_limit and FAIL
        otherwise.

        Design: Difficulty/dual_variant_calc/leak_verdict_diverges_by_method_on_same_magnitude
        """
        scenario = setup_two_brazed_high_a2l_lots(quantity_units=12)
        lot_id = scenario["build_order_2"]["id"]

        response = api.create_leak_test(
            helium_leak_test_payload(lot_id, measured_leak_rate_g_per_year=1.90),
            quality_technician_headers,
        )
        record = validate_success(response, 201)

        assert_leak_test(record)
        assert record["method"] == "HELIUM_MASS_SPEC"
        assert float(record["applied_limit"]) == pytest.approx(1.500, abs=0.0005), (
            f"3.000 g/yr halved for an A2L lot is 1.500, got {record['applied_limit']}"
        )
        assert record["verdict"] == "FAIL", "1.90 g/yr is above the 1.500 g/yr limit"

        lot = read_build_order(lot_id)
        assert lot["status"] == "REWORK"
        assert lot["latest_leak_verdict"] == "FAIL"
        assert lot["rework_count"] == 1, "a first failure costs one unit of the budget"

        items, meta = validate_paginated(
            api.list_build_order_leak_tests(lot_id, quality_technician_headers)
        )
        assert meta["total_count"] == 1, "the failing lot holds exactly one leak test"
        assert items[0]["method"] == "HELIUM_MASS_SPEC"

    def test_same_magnitude_passes_by_pressure_decay_and_fails_by_helium(
        self, api, quality_technician_headers
    ):
        """The two variants share the strictness factor and the "at or below"
        comparison direction, but they consume different measurement fields,
        different constants, and different physical units, so one variant's
        applied_limit is never a meaningful limit for the other.

        Design: Difficulty/dual_variant_calc/leak_verdict_diverges_by_method_on_same_magnitude
        """
        scenario = setup_two_brazed_high_a2l_lots(quantity_units=12)
        first_lot_id = scenario["build_order_1"]["id"]
        second_lot_id = scenario["build_order_2"]["id"]

        decay_record = validate_success(
            api.create_leak_test(
                pressure_decay_leak_test_payload(
                    first_lot_id, decay_kpa=1.90, hold_minutes=30
                ),
                quality_technician_headers,
            ),
            201,
        )
        helium_record = validate_success(
            api.create_leak_test(
                helium_leak_test_payload(
                    second_lot_id, measured_leak_rate_g_per_year=1.90
                ),
                quality_technician_headers,
            ),
            201,
        )

        assert decay_record["verdict"] == "PASS"
        assert helium_record["verdict"] == "FAIL"
        assert float(decay_record["applied_limit"]) == pytest.approx(2.00, abs=0.001)
        assert float(helium_record["applied_limit"]) == pytest.approx(1.500, abs=0.0005)

        assert read_build_order(first_lot_id)["status"] == "LEAK_PASSED"
        assert read_build_order(second_lot_id)["status"] == "REWORK"


class TestRepairBudgetExhaustion:
    """Two repairs are allowed; the third failure ends the lot."""

    def test_two_failed_leak_cycles_leave_the_lot_repairable_at_brazed(
        self, api, quality_technician_headers
    ):
        """A FAIL costs the lot one unit of a repair budget of two:
        rework_count increases by one, and if the incremented count is 2 or
        below the lot goes BRAZED → REWORK with latest_leak_verdict set to FAIL.

        Design: Difficulty/non_linear_state_machine/third_leak_failure_scraps_lot_after_two_rework_cycles
        """
        scenario = setup_lot_after_two_failed_leak_cycles(quantity_units=20)
        lot = scenario["build_order"]

        assert lot["status"] == "BRAZED", "the repaired lot is brazed again"
        assert lot["rework_count"] == 2, "two failures have been charged to the budget"
        assert lot["latest_leak_verdict"] == "FAIL"

        items, meta = validate_paginated(
            api.list_build_order_leak_tests(lot["id"], quality_technician_headers)
        )
        assert meta["total_count"] == 2, "both failures are retained as records"
        assert [row["verdict"] for row in items] == ["FAIL", "FAIL"]

    def test_third_leak_failure_scraps_the_lot_with_the_rework_limit_reason(
        self, api, quality_technician_headers
    ):
        """If the increment would take rework_count past 2 — that is, on the
        third failure of the lot across leak and run testing combined — the lot
        goes BRAZED → SCRAPPED instead, with closed_reason set to
        REWORK_LIMIT_EXCEEDED and latest_leak_verdict set to FAIL.

        Design: Difficulty/non_linear_state_machine/third_leak_failure_scraps_lot_after_two_rework_cycles
        """
        scenario = setup_lot_after_two_failed_leak_cycles(quantity_units=20)
        lot_id = scenario["build_order"]["id"]

        record = validate_success(
            api.create_leak_test(
                pressure_decay_leak_test_payload(lot_id, decay_kpa=2.80, hold_minutes=30),
                quality_technician_headers,
            ),
            201,
        )
        assert record["verdict"] == "FAIL"
        assert float(record["applied_limit"]) == pytest.approx(2.00, abs=0.001)

        lot = read_build_order(lot_id)
        assert lot["status"] == "SCRAPPED", "the third failure ends the lot"
        assert lot["closed_reason"] == "REWORK_LIMIT_EXCEEDED"
        assert lot["latest_leak_verdict"] == "FAIL"

        _, meta = validate_paginated(
            api.list_build_order_leak_tests(lot_id, quality_technician_headers)
        )
        assert meta["total_count"] == 3, "all three failing tests survive as records"

    def test_scrapped_lot_refuses_to_re_enter_fabrication(
        self, api, quality_technician_headers, production_technician_headers
    ):
        """Starting fabrication advances DRAFT → COIL_FAB, and the very same
        action advances REWORK → COIL_FAB for a lot sent back for repair, which
        is what closes the repair cycle COIL_FAB → BRAZED → REWORK → COIL_FAB.
        Either way the lot must be in DRAFT or REWORK, otherwise
        ERR_BUILD_STAGE_INVALID, and the platform must still be RELEASED,
        otherwise ERR_INVALID_PLATFORM_STATE.

        Design: Difficulty/non_linear_state_machine/third_leak_failure_scraps_lot_after_two_rework_cycles
        """
        scenario = setup_lot_after_two_failed_leak_cycles(quantity_units=20)
        lot_id = scenario["build_order"]["id"]
        validate_success(
            api.create_leak_test(
                pressure_decay_leak_test_payload(lot_id, decay_kpa=2.80, hold_minutes=30),
                quality_technician_headers,
            ),
            201,
        )
        assert read_build_order(lot_id)["status"] == "SCRAPPED"

        response = api.start_coil_fab(lot_id, production_technician_headers)
        validate_error(response, "ERR_BUILD_STAGE_INVALID", 409)
        assert read_build_order(lot_id)["status"] == "SCRAPPED"


class TestChargingGateOrder:
    """The build-stage gate is reached before the flammable charge ceiling."""

    def test_over_limit_charge_on_a_brazed_lot_is_reported_as_a_stage_error(
        self, api, production_technician_headers
    ):
        """Charging an over-limit mass onto a lot that has not passed its leak
        test returns ERR_BUILD_STAGE_INVALID; the safety limit is reported only
        for a lot that is otherwise chargeable.

        Design: Difficulty/priority_pair_validation_conflict/charge_stage_gate_preempts_flammable_charge_limit
        """
        scenario = setup_brazed_high_a2l_lot(quantity_units=20)
        lot_id = scenario["build_order"]["id"]
        assert scenario["platform"]["max_charge_grams"] == 1800

        response = api.charge_build_order(
            lot_id, charge_payload(5000), production_technician_headers
        )
        validate_error(response, "ERR_BUILD_STAGE_INVALID", 409)

        lot = read_build_order(lot_id)
        assert lot["status"] == "BRAZED", "the refused charge left the stage alone"
        assert lot["charge_grams"] == 0, "no partial write is left behind"

    def test_over_limit_charge_on_a_leak_passed_lot_is_reported_as_a_safety_error(
        self, api, quality_technician_headers, production_technician_headers
    ):
        """When the platform's program carries flammability_class A2L, the
        charge_grams supplied on the request must not exceed the platform's
        max_charge_grams, otherwise the charge is refused with
        ERR_FLAMMABLE_CHARGE_LIMIT_EXCEEDED.

        Design: Difficulty/priority_pair_validation_conflict/charge_stage_gate_preempts_flammable_charge_limit
        """
        scenario = setup_brazed_high_a2l_lot(quantity_units=20)
        lot_id = scenario["build_order"]["id"]
        validate_success(
            api.create_leak_test(
                helium_leak_test_payload(lot_id, measured_leak_rate_g_per_year=1.20),
                quality_technician_headers,
            ),
            201,
        )
        assert read_build_order(lot_id)["status"] == "LEAK_PASSED"

        response = api.charge_build_order(
            lot_id, charge_payload(5000), production_technician_headers
        )
        validate_error(response, "ERR_FLAMMABLE_CHARGE_LIMIT_EXCEEDED", 422)

        lot = read_build_order(lot_id)
        assert lot["status"] == "LEAK_PASSED"
        assert lot["charge_grams"] == 0

    def test_identical_charge_request_changes_error_once_the_lot_is_chargeable(
        self, api, quality_technician_headers, production_technician_headers
    ):
        """On charging a lot, the build-stage gate is checked before the
        flammable-charge safety limit.

        Design: Difficulty/priority_pair_validation_conflict/charge_stage_gate_preempts_flammable_charge_limit
        """
        scenario = setup_brazed_high_a2l_lot(quantity_units=20)
        lot_id = scenario["build_order"]["id"]
        payload = charge_payload(5000)

        first = api.charge_build_order(lot_id, payload, production_technician_headers)
        validate_error(first, "ERR_BUILD_STAGE_INVALID", 409)

        leak_record = validate_success(
            api.create_leak_test(
                helium_leak_test_payload(lot_id, measured_leak_rate_g_per_year=1.20),
                quality_technician_headers,
            ),
            201,
        )
        assert leak_record["verdict"] == "PASS"
        assert_instant_equals(
            leak_record["performed_at"], "2026-08-01T00:00:00Z", "performed_at"
        )

        second = api.charge_build_order(lot_id, payload, production_technician_headers)
        validate_error(second, "ERR_FLAMMABLE_CHARGE_LIMIT_EXCEEDED", 422)
        assert read_build_order(lot_id)["charge_grams"] == 0
