"""Shelf-stocking allocation and immediate post-delivery visibility
(PRD §3.6, §2.6)."""
from test_helpers import (
    make_driver_headers,
    setup_delivered_stop_scenario,
    setup_dispatched_route_scenario,
    validate_success,
)


class TestStockingAllocationNestedMinMax:
    def test_stocked_is_min_of_delivered_and_shelf_room(self, api):
        """PRD §3.6: "`stocked_units` is the smaller of `delivered_units` and
        the room left on the shelf (the store's `shelf_capacity_units` minus
        `on_shelf_units_observed`, floored at zero)."

        Design: Difficulty/combinatorial_formula/stocking_allocation_nested_minmax
        """
        ctx = setup_dispatched_route_scenario(plant_name="Plant Eps", order_qty=100)
        stop = ctx["stop"]
        driver = ctx["driver"]

        delivered = validate_success(
            api.deliver_route_stop(
                stop["id"],
                {"delivered_units": 90, "on_shelf_units_observed": 30},
                make_driver_headers(driver["id"]),
            )
        )
        # min(90, max(0, 100-30)) = min(90, 70) = 70
        assert delivered["stocked_units"] == 70, (
            f"stocked must be min(90, max(0,100-30))=70, got {delivered['stocked_units']}"
        )

    def test_refused_is_delivered_minus_stocked(self, api):
        """PRD §3.6: "`refused_units` is the remainder of `delivered_units`
        that did not fit."

        Design: Difficulty/combinatorial_formula/stocking_allocation_nested_minmax
        """
        ctx = setup_dispatched_route_scenario(plant_name="Plant Eps 2", order_qty=100)
        stop = ctx["stop"]
        driver = ctx["driver"]

        delivered = validate_success(
            api.deliver_route_stop(
                stop["id"],
                {"delivered_units": 90, "on_shelf_units_observed": 30},
                make_driver_headers(driver["id"]),
            )
        )
        assert delivered["refused_units"] == 20, (
            f"refused must be 90-70=20, got {delivered['refused_units']}"
        )
        assert delivered["status"] == "DELIVERED"


class TestImmediateVisibilityAfterDeliver:
    def test_immediate_visibility_after_deliver(self, api):
        """PRD §2.6: "all such cascades apply immediately, within the same
        request." PRD §3.6: "The route accumulates both figures:
        `delivered_units` grows by the stop's delivered amount and
        `refused_units` by the refused amount, while the stop moves from
        `PENDING` to `DELIVERED`."

        Design: Corner/consistency_model/immediate_visibility_after_deliver
        """
        ctx = setup_dispatched_route_scenario(plant_name="Plant P", order_qty=100)
        stop = ctx["stop"]
        route = ctx["route"]
        driver = ctx["driver"]

        delivered_stop = validate_success(
            api.deliver_route_stop(
                stop["id"],
                {"delivered_units": 90, "on_shelf_units_observed": 30},
                make_driver_headers(driver["id"]),
            )
        )
        assert delivered_stop["stocked_units"] == 70

        # Read the route in the same request scope — no close_day or recompute
        # needed; the accrual is already visible.
        from test_helpers import TEST_USERS
        route_after = validate_success(
            api.get_route(route["id"], TEST_USERS["planner_headers"])
        )
        assert route_after["delivered_units"] == 90, (
            f"route.delivered_units must already be 90, got {route_after['delivered_units']}"
        )
        assert route_after["refused_units"] == 20, (
            f"route.refused_units must already be 20, got {route_after['refused_units']}"
        )
