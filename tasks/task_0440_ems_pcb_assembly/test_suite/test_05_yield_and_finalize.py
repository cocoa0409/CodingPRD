"""First-pass yield computation and the finalize-test PASSED / FAILED branch.

Covers the queue-A boundary-precision instance on first_pass_yield_pct crossing the
70-percent floor at finalize-test.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def test_fpy_exactly_at_floor_finalizes_passed(api):
    """PRD §3.8: "If instead the recomputed `first_pass_yield_pct` is below the
    minimum acceptable first-pass yield of 70 percent, the work order transitions from
    `AT_TEST` to `FAILED`."
    PRD §3.8: "If every unit under the work order has reached `quality_status` `PASS`
    or `REWORKED` — none remaining `BUILT` or `FAIL` — the work order transitions from
    `AT_TEST` to `PASSED`."

    Boundary: planned 10 with 7 first-pass PASS (rework_count 0) and 3 reworked-from-
    fail (rework_count 1) gives FPY 7/10 == 70.00, exactly at (>=) the floor, and every
    unit is PASS/REWORKED, so finalize-test -> PASSED.

    Design: Difficulty/boundary_precision_check/fpy_exactly_at_min_yield_threshold_passes
    """
    # Stock covers the 10 build draws plus 3 rework replacement draws.
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=100, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    program = fx.create_verified_program(bom["id"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=10)
    get_success_data(api.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    get_success_data(api.start_work_order(wo["id"], PP))
    get_success_data(api.build_and_test_units(
        f.build_and_test_payload(wo["id"], pass_first_count=7,
                                 rework_from_fail_count=3,
                                 replacement_part_id=part["id"]), PP))

    finalized = validate_success(api.finalize_test(wo["id"], QE))
    assert finalized["first_pass_yield_pct"] == 70.00, finalized
    assert finalized["status"] == "PASSED", finalized


def test_fpy_below_floor_finalizes_failed(api):
    """PRD §3.8: "If instead the recomputed `first_pass_yield_pct` is below the
    minimum acceptable first-pass yield of 70 percent, the work order transitions from
    `AT_TEST` to `FAILED`."
    PRD §3.7: "The `first_pass_yield_pct` is the first-pass population divided by the
    tested population, multiplied by 100, carried to two decimal places and rounded
    half-up; when no units have been tested yet the value is zero."

    Boundary: planned 2 with 1 PASS and 1 FAIL (left FAIL, not reworked) gives FPY
    1/2 == 50.00, below the 70 floor, so finalize-test branches to FAILED.

    Design: Difficulty/boundary_precision_check/fpy_exactly_at_min_yield_threshold_passes
    """
    _part, _bom, _prog, wo, units = fx.setup_at_test_work_order(planned_qty=2,
                                                                received_qty=10,
                                                                unit_cost_cents=10,
                                                                standard_cost_cents=10)
    fx.record_result(units[0]["id"], "PASS")
    fx.record_result(units[1]["id"], "FAIL", defect_code="OPEN")
    finalized = validate_success(api.finalize_test(wo["id"], QE))
    assert finalized["first_pass_yield_pct"] == 50.00, finalized
    assert finalized["status"] == "FAILED", finalized
