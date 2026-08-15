"""Serialized harnesses and electrical testing: build stamping and serials,
test result thresholds, hipot class floors, rework cycles and the rework cap,
shipping gates, bubble-up completion, and immediate counter consistency."""
from test_helpers import (
    ApiErrorId,
    assert_harness_unit,
    complete_rework_cycle,
    fail_unit_into_rework,
    get_success_data,
    make_certification,
    make_operator,
    pass_unit_tests,
    record_continuity,
    record_hipot,
    scrap_unit,
    setup_order_in_build,
    ship_unit,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import make_line_operator_headers, make_quality_inspector_headers

PLAN = TEST_USERS["production_planner_headers"]
SHIP = TEST_USERS["shipping_clerk_headers"]


class TestBuildAndBubbleUp:
    def test_entity_backed_identity_stamps_built_by_and_serial(self, api):
        """PRD §2.1: "The same rule applies when `X-User-Role` is `LineOperator`: `X-User-ID` is the `id` of the acting `Operator`, and it is stamped onto each built harness as `built_by_operator_id`."
        PRD §3.7: "The server mints the unit's `serial_number` as the order's `order_code`, a hyphen, and the current `next_unit_seq` zero-padded to four digits — serial numbers are never reused, even after the corresponding unit is scrapped, because `next_unit_seq` only advances."

        Design: Corner/rbac/c_entity_backed_identity_stamps_built_by
        """
        ctx = setup_order_in_build(api, tag="R2", qty_ordered=2, units=0,
                                   order_code="BO-R2")
        builder = ctx["builder"]
        unit1 = validate_success(
            api.create_harness_unit(
                ctx["order"]["id"], make_line_operator_headers(builder["id"])
            ),
            201,
        )
        unit2 = validate_success(
            api.create_harness_unit(
                ctx["order"]["id"], make_line_operator_headers(builder["id"])
            ),
            201,
        )
        assert_harness_unit(unit1)
        assert unit1["built_by_operator_id"] == builder["id"], (
            f"the creating LineOperator's X-User-ID is stamped: {unit1}"
        )
        assert unit1["serial_number"] == "BO-R2-0001", (
            f"first serial minted from next_unit_seq == 1: {unit1}"
        )
        assert unit2["serial_number"] == "BO-R2-0002", (
            f"serials advance sequentially and are never reused: {unit2}"
        )

    def test_immediate_consistency_read_after_write(self, api):
        """PRD §3.7: "The unit's `built_by_operator_id` is stamped from the acting operator's `X-User-ID`, its `drawing_revision_built` is copied from the order's `drawing_revision_pinned`, both `continuity_pass` and `hipot_pass` start false, `rework_count` starts at zero, and the unit is born `BUILT`."
        PRD §3.7: "Each build recomputes the order counters, and when `qty_built` plus `qty_scrapped` reaches `qty_ordered` the order advances `IN_BUILD → TESTING`."

        Design: Corner/consistency_model/c_immediate_consistency_read_after_write
        """
        ctx = setup_order_in_build(api, tag="M1", qty_ordered=1, units=0)
        unit = validate_success(
            api.create_harness_unit(
                ctx["order"]["id"], make_line_operator_headers(ctx["builder"]["id"])
            ),
            201,
        )
        assert unit["status"] == "BUILT", f"the create response shows the born-BUILT unit: {unit}"
        order = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order["qty_built"] == 1, f"counters reconciled in the same request: {order}"
        assert order["status"] == "TESTING", (
            f"qty_built + qty_scrapped == qty_ordered advances the order: {order}"
        )

    def test_build_order_bubble_up_completion(self, api):
        """PRD §3.7: "Each build recomputes the order counters, and when `qty_built` plus `qty_scrapped` reaches `qty_ordered` the order advances `IN_BUILD → TESTING`."
        PRD §3.7: "Every transition into `TEST_PASS` runs the order's completion bubble-up: when every unit of a `TESTING` order sits in `TEST_PASS`, `SHIPPED`, or `SCRAPPED` and `qty_built` is at least 1, the order completes `TESTING → COMPLETED`."
        PRD §3.7: "When both flags stand true, the unit advances: from `BUILT` it moves to `TEST_PASS`; from `SUSPECT` it returns to `TEST_PASS` only when both a passing continuity record and a passing hipot record carry `tested_at` at or after the unit's `suspect_marked_at`, and the return clears `suspect_marked_at`."

        Design: Corner/state_machines/c_build_order_bubble_up_completion
        """
        ctx = setup_order_in_build(api, tag="S5", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        mid = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert mid["status"] == "TESTING", (
            f"building the only unit flipped IN_BUILD -> TESTING: {mid}"
        )
        pass_unit_tests(api, unit["id"], inspector["id"])
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["status"] == "TEST_PASS", f"both flags true -> TEST_PASS: {unit_after}"
        order_after = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert order_after["status"] == "COMPLETED", (
            f"every unit terminal-or-passing completes the order: {order_after}"
        )


class TestElectricalTestThresholds:
    def test_test_result_boundaries(self, api):
        """PRD §3.7: "The record's `result` derives from the measurement: a continuity test passes when `opens_count` is zero and fails otherwise; a hipot test passes when `measured_leakage_ua` is at most `leakage_limit_ua` — the boundary is inclusive — and fails otherwise."
        PRD §3.7: "A failing record drives the unit from `BUILT`, `REWORK`, or `SUSPECT` into `REWORK`, resets the failed test type's flag to false, and clears `suspect_marked_at` if it was set."

        Design: Corner/calculations/c_test_result_boundaries
        """
        ctx = setup_order_in_build(api, tag="C1", qty_ordered=2, units=2)
        inspector = ctx["line"]["inspector"]
        u1, u2 = ctx["units"]
        continuity_pass = record_continuity(api, u1["id"], inspector["id"], opens_count=0)
        assert continuity_pass["result"] == "PASS", f"opens_count == 0 passes: {continuity_pass}"
        hipot_eq = record_hipot(
            api, u1["id"], inspector["id"], measured_leakage_ua=10.0, leakage_limit_ua=10.0
        )
        assert hipot_eq["result"] == "PASS", f"leakage == limit passes (inclusive): {hipot_eq}"
        continuity_fail = record_continuity(api, u2["id"], inspector["id"], opens_count=1)
        assert continuity_fail["result"] == "FAIL", f"one open net fails continuity: {continuity_fail}"
        hipot_fail = record_hipot(
            api, u2["id"], inspector["id"], measured_leakage_ua=11.0, leakage_limit_ua=10.0
        )
        assert hipot_fail["result"] == "FAIL", f"11.0 uA exceeds the 10.0 uA limit: {hipot_fail}"
        u1_after = get_success_data(api.get_harness_unit(u1["id"], PLAN))
        u2_after = get_success_data(api.get_harness_unit(u2["id"], PLAN))
        assert u1_after["status"] == "TEST_PASS", f"both flags true -> TEST_PASS: {u1_after}"
        assert u2_after["status"] == "REWORK", f"failing records drive the unit into REWORK: {u2_after}"

    def test_hipot_voltage_class_minimum_rejected(self, api):
        """PRD §3.7: "Third, for hipot tests only, the applied `hipot_voltage_v` must meet the class floor — 500 volts for `IPC_CLASS_1`, 1000 volts for `IPC_CLASS_2`, 1500 volts for `IPC_CLASS_3` — and a voltage below the floor rejects with `ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN` before any result is recorded."

        Design: Corner/calculations/c_hipot_voltage_class_minimum_rejected
        """
        ctx = setup_order_in_build(
            api, tag="C2", qty_ordered=1, units=1,
            line_kwargs={"workmanship_class": "IPC_CLASS_3"},
        )
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        record_continuity(api, unit["id"], inspector["id"], opens_count=0)
        # 1499 V is below the 1500 V class-3 floor: rejected, nothing recorded.
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "HIPOT",
                "hipot_voltage_v": 1499.0,
                "dwell_seconds": 2.0,
                "measured_leakage_ua": 5.0,
                "leakage_limit_ua": 10.0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN)
        # Exactly 1500 V meets the floor; the passing result flips the unit.
        ok = record_hipot(
            api, unit["id"], inspector["id"],
            hipot_voltage_v=1500.0, measured_leakage_ua=5.0, leakage_limit_ua=10.0,
        )
        assert ok["result"] == "PASS", f"1500 V meets the class-3 floor: {ok}"
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["status"] == "TEST_PASS", f"both flags true -> TEST_PASS: {unit_after}"


class TestReworkCycles:
    def test_rework_limit_boundary_rejected(self, api):
        """PRD §3.7: "A `LineOperator` completes a rework cycle on a unit in `REWORK`, returning it to `BUILT` with `rework_count` incremented by one and both test flags reset to false; completing rework when `rework_count` has already reached 2 is rejected with `ERR_REWORK_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/c_rework_limit_boundary_rejected
        """
        ctx = setup_order_in_build(api, tag="S6", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        builder = ctx["builder"]
        fail_unit_into_rework(api, unit["id"], inspector["id"], opens_count=1)
        cycle1 = complete_rework_cycle(api, unit["id"], builder["id"])
        assert cycle1["rework_count"] == 1 and cycle1["status"] == "BUILT"
        fail_unit_into_rework(api, unit["id"], inspector["id"], opens_count=2)
        cycle2 = complete_rework_cycle(api, unit["id"], builder["id"])
        assert cycle2["rework_count"] == 2 and cycle2["status"] == "BUILT"
        fail_unit_into_rework(api, unit["id"], inspector["id"], opens_count=1)
        # rework_count has already reached 2: the third completion is refused.
        resp = api.complete_rework(unit["id"], make_line_operator_headers(builder["id"]))
        validate_error(resp, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED)
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["rework_count"] == 2 and unit_after["status"] == "REWORK", (
            f"the rejected completion changes nothing: {unit_after}"
        )

    def test_rework_cycle_increments_count_and_resets_flags(self, api):
        """PRD §3.7: "A failing record drives the unit from `BUILT`, `REWORK`, or `SUSPECT` into `REWORK`, resets the failed test type's flag to false, and clears `suspect_marked_at` if it was set."
        PRD §3.7: "A `LineOperator` completes a rework cycle on a unit in `REWORK`, returning it to `BUILT` with `rework_count` incremented by one and both test flags reset to false; completing rework when `rework_count` has already reached 2 is rejected with `ERR_REWORK_LIMIT_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/harness_unit_build_rework_cycle
        """
        ctx = setup_order_in_build(api, tag="NL1", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        builder = ctx["builder"]
        r1 = fail_unit_into_rework(api, unit["id"], inspector["id"], opens_count=1)
        assert r1["result"] == "FAIL", f"opens_count 1 fails continuity: {r1}"
        cycle1 = complete_rework_cycle(api, unit["id"], builder["id"])
        assert cycle1["status"] == "BUILT" and cycle1["rework_count"] == 1
        assert cycle1["continuity_pass"] is False and cycle1["hipot_pass"] is False, (
            f"re-entry to BUILT resets both test flags: {cycle1}"
        )
        r2 = record_hipot(
            api, unit["id"], inspector["id"], measured_leakage_ua=11.0, leakage_limit_ua=10.0
        )
        assert r2["result"] == "FAIL", f"11.0 uA over the 10.0 uA limit fails hipot: {r2}"
        mid = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert mid["status"] == "REWORK" and mid["hipot_pass"] is False, (
            f"the failed hipot drives REWORK and clears the hipot flag: {mid}"
        )
        cycle2 = complete_rework_cycle(api, unit["id"], builder["id"])
        assert cycle2["status"] == "BUILT" and cycle2["rework_count"] == 2, (
            f"two completed cycles accumulate rework_count 0 -> 1 -> 2: {cycle2}"
        )

    def test_rework_cycle_completes_to_test_pass(self, api):
        """PRD §3.7: "A failing record drives the unit from `BUILT`, `REWORK`, or `SUSPECT` into `REWORK`, resets the failed test type's flag to false, and clears `suspect_marked_at` if it was set."
        PRD §3.7: "When both flags stand true, the unit advances: from `BUILT` it moves to `TEST_PASS`; from `SUSPECT` it returns to `TEST_PASS` only when both a passing continuity record and a passing hipot record carry `tested_at` at or after the unit's `suspect_marked_at`, and the return clears `suspect_marked_at`."

        Design: Difficulty/non_linear_state_machine/harness_unit_build_rework_cycle
        """
        ctx = setup_order_in_build(api, tag="NL1B", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        builder = ctx["builder"]
        fail_unit_into_rework(api, unit["id"], inspector["id"], opens_count=1)
        complete_rework_cycle(api, unit["id"], builder["id"])
        record_hipot(api, unit["id"], inspector["id"],
                     measured_leakage_ua=11.0, leakage_limit_ua=10.0)
        complete_rework_cycle(api, unit["id"], builder["id"])
        # BUILT -> REWORK -> BUILT -> REWORK -> BUILT, then a clean pass pair.
        pass_unit_tests(api, unit["id"], inspector["id"])
        final = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert final["status"] == "TEST_PASS", f"cyclic machine reached TEST_PASS: {final}"
        assert final["rework_count"] == 2, f"two completed rework loops: {final}"
        assert final["continuity_pass"] is True and final["hipot_pass"] is True, (
            f"passing records set both flags: {final}"
        )


class TestShipAndTestabilityGates:
    def test_ship_requires_test_pass(self, api):
        """PRD §3.7: "Shipping is the happy-path exit: a `ShippingClerk` ships a unit in `TEST_PASS`, moving it to the terminal `SHIPPED`; shipping a unit in any other status rejects with `ERR_UNIT_NOT_SHIPPABLE`."

        Design: Corner/state_machines/c_ship_requires_test_pass
        """
        ctx = setup_order_in_build(api, tag="S7", qty_ordered=2, units=1)
        unit = ctx["units"][0]
        resp = api.ship_harness_unit(unit["id"], SHIP)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_SHIPPABLE)
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["status"] == "BUILT", f"an untested unit cannot ship: {unit_after}"

    def test_shipped_unit_rejects_electrical_test(self, api):
        """PRD §3.7: "The unit must be `BUILT`, `REWORK`, or `SUSPECT`; testing a unit in any other status rejects with `ERR_HARNESS_NOT_TESTABLE`."
        PRD §3.7: "Shipping is the happy-path exit: a `ShippingClerk` ships a unit in `TEST_PASS`, moving it to the terminal `SHIPPED`; shipping a unit in any other status rejects with `ERR_UNIT_NOT_SHIPPABLE`."

        Design: Difficulty/cross_entity_state_dependency/electrical_test_gated_by_harness_unit_state
        """
        ctx = setup_order_in_build(api, tag="CE1", qty_ordered=1, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        pass_unit_tests(api, unit["id"], inspector["id"])
        ship_unit(api, unit["id"])
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HARNESS_NOT_TESTABLE)

    def test_test_pass_unit_rejects_further_testing(self, api):
        """PRD §3.7: "The unit must be `BUILT`, `REWORK`, or `SUSPECT`; testing a unit in any other status rejects with `ERR_HARNESS_NOT_TESTABLE`."

        Design: Difficulty/cross_entity_state_dependency/electrical_test_gated_by_harness_unit_state
        """
        ctx = setup_order_in_build(api, tag="CE1T", qty_ordered=2, units=1)
        unit = ctx["units"][0]
        inspector = ctx["line"]["inspector"]
        pass_unit_tests(api, unit["id"], inspector["id"])
        # TEST_PASS is not in {BUILT, REWORK, SUSPECT}: the same certified
        # inspector and well-formed payload are rejected on unit state alone.
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(inspector["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HARNESS_NOT_TESTABLE)


class TestSegregationAndScrapCosts:
    def test_sod_builder_cannot_test(self, api):
        """PRD §2.9: "The plant enforces segregation of duties on serialized product: the operator who built a harness may not be the operator who records its electrical test."
        PRD §3.7: "Second, segregation of duties: the `test_operator_id` must differ from the unit's `built_by_operator_id`, else `ERR_SOD_BUILDER_CANNOT_TEST`."

        Design: Corner/rbac/c_sod_builder_cannot_test
        """
        line_inspector_ctx = setup_order_in_build(api, tag="R1", qty_ordered=1, units=0)
        inspector = line_inspector_ctx["line"]["inspector"]
        # The builder also holds a class-2 certification, so the certification
        # gate passes and the segregation-of-duties gate is the one that fires.
        builder = make_operator(api, name="OP One R1", badge="B-OP1-R1")
        make_certification(api, operator_id=builder["id"], workmanship_class="IPC_CLASS_2")
        unit = validate_success(
            api.create_harness_unit(
                line_inspector_ctx["order"]["id"], make_line_operator_headers(builder["id"])
            ),
            201,
        )
        resp = api.create_electrical_test_record(
            {
                "harness_unit_id": unit["id"],
                "test_type": "CONTINUITY",
                "opens_count": 0,
            },
            make_quality_inspector_headers(builder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_BUILDER_CANNOT_TEST)
        ok = record_continuity(api, unit["id"], inspector["id"], opens_count=0)
        assert ok["result"] == "PASS", f"a different certified inspector may test: {ok}"
        unit_after = get_success_data(api.get_harness_unit(unit["id"], PLAN))
        assert unit_after["continuity_pass"] is True

    def test_standard_cost_excludes_scrapped_units(self, api):
        """PRD §3.5: "The `standard_cost_cents` is `qty_built` multiplied by the per-harness standard cost — the sum, over the pinned BOM lines, of `qty_per_harness` times `unit_cost_cents` — and serves as the quoting and variance baseline."
        PRD §3.5: "The `qty_built` counter is the count of the order's harness units in `BUILT`, `TEST_PASS`, `REWORK`, `SUSPECT`, or `SHIPPED`; `qty_scrapped` counts units in `SCRAPPED`."
        PRD §3.7: "Third, the order's `qty_built`, `qty_scrapped`, and `standard_cost_cents` recompute, and the order-level checks run: `IN_BUILD → TESTING` when the sum reaches `qty_ordered`, `TESTING → CANCELLED` when `qty_built` has fallen to zero (every built unit scrapped), and the completion check above."

        Design: Corner/calculations/c_standard_cost_excludes_scrapped_units
        """
        bom = [
            {"find_number": "T1", "component_type": "TERMINAL", "mpn": "TERM-20",
             "qty_per_harness": 2, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 100},
            {"find_number": "W1", "component_type": "WIRE", "mpn": "WIRE-20",
             "qty_per_harness": 1, "supply_type": "FACTORY_STOCK", "unit_cost_cents": 50},
        ]
        ctx = setup_order_in_build(api, tag="C5", qty_ordered=2, units=2,
                                   line_kwargs={"bom": bom})
        inspector = ctx["line"]["inspector"]
        u1 = ctx["units"][0]
        # Per-harness standard cost: 2 x 100 + 1 x 50 = 250; two built units -> 500.
        before = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert before["standard_cost_cents"] == 500, f"2 x 250 cents: {before}"
        scrap_unit(api, u1["id"], inspector["id"], reason="DAMAGE")
        after = get_success_data(api.get_build_order(ctx["order"]["id"], PLAN))
        assert after["standard_cost_cents"] == 250, (
            f"the scrapped unit leaves the standard-cost input set: {after}"
        )
        assert after["qty_built"] == 1 and after["qty_scrapped"] == 1, (
            f"one surviving unit and one scrapped: {after}"
        )
