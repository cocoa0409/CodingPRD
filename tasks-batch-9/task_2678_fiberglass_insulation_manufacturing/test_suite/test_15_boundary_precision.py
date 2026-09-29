"""Boundary precision: a figure landing exactly on a threshold, and a date landing
exactly on a period edge.

Queue A / boundary_precision_check.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_close, assert_field_equals
from test_helpers.test_users import (
    QUALITY_ENGINEER_USER_ID_ALT,
    channel_manager_headers,
    quality_engineer_headers,
)

# The default SKU declares R-13.0 and the per-specimen program allows a tolerance of
# 0.30, so the conformance floor sits at exactly 12.70.
ON_THE_FLOOR = [12.70, 13.10, 12.90]
ONE_HUNDREDTH_UNDER = [12.69, 13.10, 12.90]


def _sampled_run(client: InsulationApiClient) -> Dict[str, Any]:
    """A packaged run with a thermal test open against it on the per-specimen program."""
    ctx = fx.base_setup(client)
    run = fx.run_to_packaged(client, ctx["plant_id"], ctx["sku_id"], bags_produced=120)
    lot = fx.lot_for_run(client, run["id"])
    test = fx.request_thermal_test(
        client,
        run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        window_start="2026-08-03T08:00:00Z",
        window_end="2026-08-03T16:00:00Z",
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )
    ctx.update(
        {
            "run": run,
            "run_id": run["id"],
            "lot": lot,
            "lot_id": lot["id"],
            "test": test,
            "test_id": test["id"],
        }
    )
    return ctx


def test_the_weakest_specimen_sitting_exactly_on_the_floor_conforms(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "On a `PER_SPECIMEN` basis the verdict is `CONFORMING` when `min_r_value`
    is greater than or equal to the floor and `NONCONFORMING` otherwise - every single
    specimen must clear the floor."

    Design: Difficulty/boundary_precision_check/specimen_minimum_exactly_at_declared_less_tolerance_conforms
    """
    ctx = _sampled_run(client)
    assert_close(ctx["test"]["declared_r_value_at_test"], 13.0, 2, "declared_r_value_at_test")
    assert_field_equals(ctx["test"], "conformance_basis", "PER_SPECIMEN")

    result = fx.record_thermal_result(
        client, ctx["test_id"], ON_THE_FLOOR, user_id=QUALITY_ENGINEER_USER_ID_ALT
    )

    assert_close(result["min_r_value"], 12.70, 2, "min_r_value")
    assert_close(result["mean_r_value"], 12.90, 2, "mean_r_value")
    assert_field_equals(result, "specimen_count", 3)
    assert_field_equals(result, "conformance_verdict", "CONFORMING")
    assert_field_equals(result, "status", "COMPLETED")
    assert_field_equals(result, "attempt_number", 1)

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "CONFORMING")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "AVAILABLE")
    assert lot["quarantine_reason"] is None


def test_one_hundredth_below_the_floor_condemns_the_run(
    client: InsulationApiClient,
) -> None:
    """PRD 3.6: "The floor is the pinned declared value less the program's tolerance:
    subtract `r_value_tolerance` from `declared_r_value_at_test` and quantize to two
    decimal places."

    Design: Difficulty/boundary_precision_check/specimen_minimum_exactly_at_declared_less_tolerance_conforms
    """
    ctx = _sampled_run(client)

    result = fx.record_thermal_result(
        client,
        ctx["test_id"],
        ONE_HUNDREDTH_UNDER,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    assert_close(result["min_r_value"], 12.69, 2, "min_r_value")
    # The mean is untouched by the boundary: only the minimum faces the floor here.
    assert_close(result["mean_r_value"], 12.90, 2, "mean_r_value")
    assert_field_equals(result, "conformance_verdict", "NONCONFORMING")
    assert_field_equals(result, "status", "COMPLETED")

    run = fx.get_run(client, ctx["run_id"])
    assert_field_equals(run, "qc_status", "NONCONFORMING")

    lot = fx.get_lot(client, ctx["lot_id"])
    assert_field_equals(lot, "status", "QUARANTINED")
    assert_field_equals(lot, "quarantine_reason", "RUN_NONCONFORMING")


def test_the_floor_is_unmoved_on_a_retest_attempt(client: InsulationApiClient) -> None:
    """PRD 3.6: "A figure landing exactly on the floor conforms."

    Design: Difficulty/boundary_precision_check/specimen_minimum_exactly_at_declared_less_tolerance_conforms
    """
    ctx = _sampled_run(client)
    fx.record_thermal_result(
        client,
        ctx["test_id"],
        ONE_HUNDREDTH_UNDER,
        user_id=QUALITY_ENGINEER_USER_ID_ALT,
    )

    retest = get_success_data(
        client.request_retest(
            ctx["test_id"],
            f.retest_window_payload("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z"),
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )
    assert_field_equals(retest, "attempt_number", 2)
    assert_field_equals(retest, "status", "IN_LAB")

    result = get_success_data(
        client.record_result(
            ctx["test_id"],
            ON_THE_FLOOR,
            quality_engineer_headers(QUALITY_ENGINEER_USER_ID_ALT),
        )
    )

    assert_close(result["min_r_value"], 12.70, 2, "min_r_value")
    assert_close(result["declared_r_value_at_test"], 13.0, 2, "declared_r_value_at_test")
    assert_field_equals(result, "conformance_verdict", "CONFORMING")
    assert_field_equals(result, "attempt_number", 2)
    assert_field_equals(result, "status", "COMPLETED")


PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-31T23:59:59Z"
# One second past the exclusive period end.
JUST_AFTER_PERIOD_END = "2026-09-01T00:00:00Z"


def _cycle_with_one_late_order(client: InsulationApiClient) -> Dict[str, Any]:
    """A supplied cycle whose only order is due after the period closes."""
    ctx = fx.certified_sku_with_lot(client, bags_produced=120)
    late = fx.place_order(
        client,
        ctx["sku_id"],
        8800.0,
        channel_type="DISTRIBUTOR",
        priority_tier="CONTRACT",
        required_by=JUST_AFTER_PERIOD_END,
    )
    cycle = fx.open_cycle(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        allocation_basis="CONTRACT_FIRST",
    )
    ctx.update({"late": late, "late_id": late["id"], "cycle": cycle, "cycle_id": cycle["id"]})
    return ctx


def test_an_order_due_one_second_past_the_period_end_is_not_eligible(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "the demand set must be non-empty or the proposal is refused with
    `ERR_NO_ELIGIBLE_ORDERS` - an empty demand set is rejected rather than producing an
    empty proposal."

    Design: Difficulty/boundary_precision_check/order_required_by_exactly_at_period_end_is_eligible
    """
    ctx = _cycle_with_one_late_order(client)

    resp = client.propose_cycle(ctx["cycle_id"], channel_manager_headers())

    validate_error(resp, ApiErrors.NO_ELIGIBLE_ORDERS)

    cycle = fx.get_cycle(client, ctx["cycle_id"])
    assert_field_equals(cycle, "status", "OPEN")
    assert_close(cycle["allocated_sqft"], 0.00, 2, "allocated_sqft")
    assert cycle["total_available_sqft"] is None
    assert cycle["allocatable_sqft"] is None
    assert fx.lines_for_cycle(client, ctx["cycle_id"]) == []


def test_an_order_due_exactly_at_the_period_end_is_funded(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Demand is the set of orders whose `product_line_id` matches the cycle's,
    whose status is `SUBMITTED`, `PARTIAL` or `BACKORDERED`, whose `required_by` falls at
    or before the cycle's `period_end`, and whose remaining need - `requested_sqft` less
    `allocated_sqft` - is strictly greater than zero."

    Design: Difficulty/boundary_precision_check/order_required_by_exactly_at_period_end_is_eligible
    """
    ctx = _cycle_with_one_late_order(client)
    edge = fx.place_order(
        client,
        ctx["sku_id"],
        4400.00,
        channel_type="DISTRIBUTOR",
        priority_tier="CONTRACT",
        required_by=PERIOD_END,
    )

    cycle = fx.propose_cycle(client, ctx["cycle_id"])

    assert_field_equals(cycle, "status", "PROPOSED")
    assert_field_equals(cycle, "peak_season", True)
    assert_close(cycle["total_available_sqft"], 10560.00, 2, "total_available_sqft")
    assert_close(cycle["seasonal_reserve_sqft"], 1584.00, 2, "seasonal_reserve_sqft")
    assert_close(cycle["allocatable_sqft"], 8976.00, 2, "allocatable_sqft")
    # Only the edge order is in the demand set; the late order's 8800.00 is absent.
    assert_close(cycle["total_requested_sqft"], 4400.00, 2, "total_requested_sqft")
    assert_close(cycle["shortage_ratio"], 1.0000, 4, "shortage_ratio")
    assert_close(cycle["allocated_sqft"], 4400.00, 2, "allocated_sqft")
    assert_close(cycle["unallocated_sqft"], 4576.00, 2, "unallocated_sqft")

    edge_lines = fx.lines_for_order(client, edge["id"])
    assert len(edge_lines) == 1, "the edge order should carry exactly one proposed line"
    assert_field_equals(edge_lines[0], "status", "PROPOSED")
    assert_close(edge_lines[0]["allocated_sqft"], 4400.00, 2, "allocated_sqft")
    assert_field_equals(edge_lines[0], "bags", 50)
    assert_field_equals(edge_lines[0], "inventory_lot_id", ctx["lot_id"])

    assert fx.lines_for_order(client, ctx["late_id"]) == []
    late = fx.get_order(client, ctx["late_id"])
    assert_field_equals(late, "status", "SUBMITTED")
    assert_close(late["allocated_sqft"], 0.00, 2, "allocated_sqft")


def test_committing_the_edge_order_fills_it_to_the_bag(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "its status is **derived** from the comparison: `ALLOCATED` when
    `allocated_sqft` equals `requested_sqft` exactly, `PARTIAL` when it is greater than
    zero but short of the request, and `BACKORDERED` when it is exactly 0.00."

    Design: Difficulty/boundary_precision_check/order_required_by_exactly_at_period_end_is_eligible
    """
    ctx = _cycle_with_one_late_order(client)
    edge = fx.place_order(
        client,
        ctx["sku_id"],
        4400.00,
        channel_type="DISTRIBUTOR",
        priority_tier="CONTRACT",
        required_by=PERIOD_END,
    )
    fx.propose_cycle(client, ctx["cycle_id"])

    fx.commit_cycle(client, ctx["cycle_id"])

    filled = fx.get_order(client, edge["id"])
    assert_close(filled["allocated_sqft"], 4400.00, 2, "allocated_sqft")
    assert_close(filled["fill_rate_pct"], 100.00, 2, "fill_rate_pct")
    assert_field_equals(filled, "status", "ALLOCATED")

    # The ineligible order is still waiting, untouched by the commit.
    late = fx.get_order(client, ctx["late_id"])
    assert_field_equals(late, "status", "SUBMITTED")
    assert_close(late["allocated_sqft"], 0.00, 2, "allocated_sqft")
