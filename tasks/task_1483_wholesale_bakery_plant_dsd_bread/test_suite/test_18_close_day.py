"""Close-of-day ops-run checkpoint and stop-reconcile order cascade
(PRD §2.4, §3.6)."""
from test_helpers import (
    TEST_USERS,
    make_driver_headers,
    set_clock,
    setup_delivered_stop_scenario,
    setup_settled_route_scenario,
    setup_verified_stale_return_scenario,
    validate_success,
    create_stale_return,
    make_qa_headers,
)


class TestStopReconcileCascadesOrderFulfilled:
    def test_stop_reconcile_cascades_order_fulfilled(self, api):
        """PRD §3.6: "Reconciling a `DELIVERED` stop moves it to `RECONCILED`
        and cascades to the order: if the stop's `delivered_units` equal the
        order's `total_units`, a `LOCKED` order becomes `FULFILLED`."

        Design: Corner/endpoints/stop_reconcile_cascades_order_fulfilled
        """
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant P", order_qty=100, delivered_units=100,
        )
        stop = ctx["stop"]
        order = ctx["order"]

        reconciled = validate_success(
            api.reconcile_route_stop(stop["id"], TEST_USERS["planner_headers"])
        )
        assert reconciled["status"] == "RECONCILED"

        order_after = validate_success(
            api.get_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert order_after["status"] == "FULFILLED", (
            f"full-quantity reconcile must flip the order to FULFILLED, got {order_after['status']}"
        )


class TestCloseDaySuspendsHighStaleRatioStore:
    def test_close_day_suspends_high_stale_ratio_store(self, api):
        """PRD §2.4: "every `ACTIVE` store whose stale ratio is strictly
        greater than 0.15 is suspended." And: "it increments `day_index` by
        1."
        PRD §3.8: "adds the sum of the verified quantities onto the store's
        `lifetime_stale_units`."
        PRD §3.7: "Settlement also adds each stop's `delivered_units` onto
        the corresponding store's `lifetime_delivered_units`."

        Design: Corner/cross_cutting_complexity_layers/close_day_suspends_high_stale_ratio_store
        """
        # Deliver 100 units, then verify a 20-unit stale return, then settle
        # the route so lifetime_delivered_units lands at 100.
        ctx = setup_verified_stale_return_scenario(
            plant_name="Plant P Close",
            stale_lines_qty=20,
            store_overrides={"shelf_capacity_units": 500},
        )
        route = ctx["route"]
        driver = ctx["driver"]
        hdrs = make_driver_headers(driver["id"])
        validate_success(api.complete_route(route["id"], hdrs))
        validate_success(
            api.settle_route(route["id"], {}, TEST_USERS["planner_headers"])
        )

        plant = ctx["plant"]
        store = ctx["store"]
        plant_after = validate_success(
            api.close_day(plant["id"], TEST_USERS["admin_headers"])
        )
        assert plant_after["day_index"] == 1, (
            f"close_day must advance day_index by 1, got {plant_after['day_index']}"
        )

        store_after = validate_success(
            api.get_store(store["id"], TEST_USERS["planner_headers"])
        )
        # 20 stale / 100 delivered = 0.20 > 0.15.
        assert store_after["stale_ratio"] == 0.2, (
            f"stale_ratio must be 20/100 = 0.2, got {store_after['stale_ratio']}"
        )
        assert store_after["status"] == "SUSPENDED", (
            f"ratio 0.20 > 0.15 must auto-suspend at close_day, got {store_after['status']}"
        )
