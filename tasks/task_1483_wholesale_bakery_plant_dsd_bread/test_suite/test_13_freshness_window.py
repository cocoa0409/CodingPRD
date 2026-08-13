"""Freshness, return-window, planned-qty, and plan-uniqueness rejections
(PRD §3.4, §3.6, §3.8, §3.3)."""
from test_helpers import (
    TEST_USERS,
    create_order,
    create_plan,
    create_plant,
    create_product,
    create_route,
    create_store,
    create_driver,
    confirm_order,
    create_stale_return,
    lock_order,
    make_driver_headers,
    set_clock,
    setup_delivered_stop_scenario,
    setup_dispatched_route_scenario,
    setup_released_batch_scenario,
    validate_error,
    validate_success,
)


class TestFreshnessWindowViolation:
    def test_freshness_window_violation_on_late_delivery(self, api):
        """PRD §3.6: "the freshness window must hold: the delivery clock must
        be no later than the earliest `fresh_until` across the stop's
        `batch_ids` minus the store's `min_remaining_life_hours_on_delivery`
        — equality is allowed — otherwise the delivery is rejected with
        `ERR_FRESHNESS_WINDOW_VIOLATION`."

        Design: Corner/validations/freshness_window_violation_on_late_delivery
        """
        # Batch baked 2026-08-09T09:00Z, shelf 48h -> fresh_until 2026-08-11T09:00Z.
        # Store min_remaining 12h -> deliver-by 2026-08-10T21:00Z.
        ctx = setup_dispatched_route_scenario(
            plant_name="Plant P Fresh",
            order_qty=100,
            deliver_clock="2026-08-10T09:00:00Z",
        )
        stop = ctx["stop"]
        driver = ctx["driver"]

        # One second past the freshness boundary.
        set_clock("2026-08-10T21:00:01Z")
        resp = api.deliver_route_stop(
            stop["id"],
            {"delivered_units": 100, "on_shelf_units_observed": 0},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, "ERR_FRESHNESS_WINDOW_VIOLATION", expected_status=409)
        after = validate_success(
            api.get_route_stop(stop["id"], TEST_USERS["planner_headers"])
        )
        assert after["status"] == "PENDING"


class TestReturnWindowClosed:
    def test_return_window_closed_after_72h(self, api):
        """PRD §3.8: "The return window is 72 hours: a pickup recorded more
        than 72 hours after a line's `bake_completed_at` is rejected with
        `ERR_RETURN_WINDOW_CLOSED`."

        Design: Corner/validations/return_window_closed_after_72h
        """
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant P 72h",
            order_qty=100,
            bake_complete_clock="2026-08-09T09:00:00Z",
        )
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        # Age 73h (bake 2026-08-09T09:00Z, clock 2026-08-12T10:00Z).
        set_clock("2026-08-12T10:00:00Z")
        resp = api.create_stale_return(
            {"store_id": store["id"], "route_stop_id": stop["id"],
             "lines": [{"batch_id": batch["id"], "qty": 2}]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, "ERR_RETURN_WINDOW_CLOSED", expected_status=409)


class TestStopPlannedQtyMismatch:
    def test_stop_planned_qty_mismatch_rejected(self, api):
        """PRD §3.6: "`planned_units` must equal the order's `total_units`
        exactly (otherwise `ERR_PLANNED_QTY_MISMATCH`)."

        Design: Corner/validations/stop_planned_qty_mismatch_rejected
        """
        ctx = setup_released_batch_scenario(plant_name="Plant P Qty", order_qty=100)
        plant = ctx["plant"]
        driver = ctx["driver"]
        order = ctx["order"]
        batch = ctx["batch"]

        route = create_route(plant["id"], driver["id"])
        resp = api.create_route_stop(
            {"route_id": route["id"], "store_order_id": order["id"],
             "planned_units": 99, "batch_ids": [batch["id"]]},
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_PLANNED_QTY_MISMATCH", expected_status=409)


class TestDuplicatePlanDate:
    def test_duplicate_plan_date_rejected(self, api):
        """PRD §3.3: "If a plan in any state other than `DRAFT` already exists
        for the same plant and bake date, creation is rejected with
        `ERR_DUPLICATE_PLAN_DATE`."

        Design: Corner/validations/duplicate_plan_date_rejected
        """
        plant = create_plant(name="Plant P Dup")
        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        validate_success(api.lock_production_plan(plan["id"], TEST_USERS["planner_headers"]))

        plant_now = validate_success(
            api.get_plant(plant["id"], TEST_USERS["planner_headers"])
        )
        # A LOCKED (non-DRAFT) plan already exists for plant+2026-08-09.
        resp = api.create_production_plan(
            {"plant_id": plant["id"], "bake_date": "2026-08-09",
             "expected_plant_version": plant_now["version"]},
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_DUPLICATE_PLAN_DATE", expected_status=409)
