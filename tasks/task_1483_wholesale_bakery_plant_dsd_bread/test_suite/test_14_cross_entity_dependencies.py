"""Cross-entity state dependencies: batch scheduling vs line residue, route
loading vs order lock, stale-return vs stop state (PRD §3.4, §3.6, §3.8)."""
from test_helpers import (
    TEST_USERS,
    create_batch,
    create_line,
    create_order,
    create_plan,
    create_plant,
    create_product,
    create_route,
    create_stop,
    create_store,
    create_driver,
    confirm_order,
    get_plan,
    lock_order,
    lock_plan,
    make_driver_headers,
    release_plan,
    set_clock,
    setup_delivered_stop_scenario,
    setup_line_dirty_with_sesame,
    setup_released_batch_scenario,
    validate_error,
    validate_success,
    walk_batch_to_released,
)


class TestBatchScheduleGatedByLineCleanliness:
    def test_same_allergen_on_dirty_line_accepted(self, api):
        """PRD §3.4: "a batch whose allergen class differs from a `DIRTY`
        line's current residue class — with no verified changeover in between
        — is rejected with `ERR_ALLERGEN_SEGREGATION_VIOLATION`." (The
        same-class case is the complement: it is not rejected.)

        Design: Difficulty/cross_entity_state_dependency/batch_schedule_gated_by_line_cleanliness
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant Omicron")
        line = ctx["line"]
        plan = ctx["plan"]
        product_b = ctx["product_b"]

        plan_now = get_plan(plan["id"])
        ok = validate_success(
            api.create_batch(
                {
                    "production_plan_id": plan["id"],
                    "line_id": line["id"],
                    "product_id": product_b["id"],
                    "qty_units": 50,
                    "scheduled_start_at": "2026-08-09T11:00:00Z",
                    "scheduled_end_at": "2026-08-09T12:00:00Z",
                    "expected_production_plan_version": plan_now["version"],
                },
                TEST_USERS["planner_headers"],
            ),
            expected_status=201,
        )
        assert ok["status"] == "SCHEDULED", (
            "same-allergen batch on a DIRTY line must be schedulable"
        )

    def test_different_allergen_on_dirty_line_rejected(self, api):
        """PRD §3.4: "a batch whose allergen class differs from a `DIRTY`
        line's current residue class — with no verified changeover in between
        — is rejected with `ERR_ALLERGEN_SEGREGATION_VIOLATION`."

        Design: Difficulty/cross_entity_state_dependency/batch_schedule_gated_by_line_cleanliness
        """
        ctx = setup_line_dirty_with_sesame(plant_name="Plant Omicron 2")
        plant = ctx["plant"]
        line = ctx["line"]
        plan = ctx["plan"]

        # Add a NONE-allergen product to the same plant.
        product_a = create_product(plant["id"], sku="SKU-A", allergen_class="NONE")

        plan_now = get_plan(plan["id"])
        resp = api.create_batch(
            {
                "production_plan_id": plan["id"],
                "line_id": line["id"],
                "product_id": product_a["id"],
                "qty_units": 50,
                "scheduled_start_at": "2026-08-09T12:00:00Z",
                "scheduled_end_at": "2026-08-09T13:00:00Z",
                "expected_production_plan_version": plan_now["version"],
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(resp, "ERR_ALLERGEN_SEGREGATION_VIOLATION", expected_status=409)


def _confirmed_order_with_released_batch(plant_name: str):
    """One plant carrying two orders for the same product on the same
    delivery date: the first is locked and baked into a RELEASED batch; the
    second stays CONFIRMED. The stop under test is added against the
    CONFIRMED order with the released batch (stop creation accepts CONFIRMED
    per §3.6)."""
    plant = create_plant(name=plant_name)
    product_a = create_product(plant["id"])
    store = create_store(plant["id"])
    driver = create_driver(plant["id"])
    line = create_line(plant["id"])

    set_clock("2026-08-06T00:00:00Z")
    o1 = create_order(store["id"], product_a["id"], qty=100)
    confirm_order(o1["id"])
    lock_order(o1["id"])

    # Second order — CONFIRMED but NOT locked. Created and confirmed while the
    # clock is still at or before the cutoff (§3.2: confirm enforces cutoff).
    o2 = create_order(store["id"], product_a["id"], qty=100)
    confirm_order(o2["id"])

    plan = create_plan(plant["id"], expected_plant_version=plant["version"])
    locked_plan = lock_plan(plan["id"])
    batch = create_batch(
        plan["id"], line["id"], product_a["id"],
        plan_version=locked_plan["version"], qty_units=100,
    )
    release_plan(plan["id"])
    set_clock("2026-08-09T07:50:00Z")
    batch = walk_batch_to_released(batch["id"], operator_id="op-1", qa_id="qa-1")

    return {
        "plant": plant, "product_a": product_a, "store": store,
        "driver": driver, "batch": batch, "order": o2,
    }


class TestRouteLoadingGatedByOrderLock:
    def test_route_loading_blocked_by_unlocked_stop_order(self, api):
        """PRD §3.6: "Starting loading requires at least one stop on the route
        (else `ERR_INVALID_STATE`) and requires every stop's order to be
        `LOCKED` or `SHORTED` (else `ERR_STOPS_NOT_LOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/route_loading_gated_by_order_lock
        """
        ctx = _confirmed_order_with_released_batch("Plant Pi")
        route = create_route(ctx["plant"]["id"], ctx["driver"]["id"])
        create_stop(route["id"], ctx["order"]["id"], 100, [ctx["batch"]["id"]])

        resp = api.start_loading(route["id"], make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, "ERR_STOPS_NOT_LOCKED", expected_status=409)

    def test_route_loading_leaves_route_unchanged_on_rejection(self, api):
        """PRD §3.6: "Starting loading requires at least one stop on the
        route (else `ERR_INVALID_STATE`) and requires every stop's order to
        be `LOCKED` or `SHORTED` (else `ERR_STOPS_NOT_LOCKED`); it moves the
        route from `PLANNED` to `LOADING` and freezes `loaded_units` as the
        sum of the stops' `planned_units`." A rejected start-loading must
        leave the route in PLANNED.

        Design: Difficulty/cross_entity_state_dependency/route_loading_gated_by_order_lock
        """
        ctx = _confirmed_order_with_released_batch("Plant Pi 2")
        route = create_route(ctx["plant"]["id"], ctx["driver"]["id"])
        create_stop(route["id"], ctx["order"]["id"], 100, [ctx["batch"]["id"]])

        resp = api.start_loading(route["id"], make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, "ERR_STOPS_NOT_LOCKED", expected_status=409)

        route_after = validate_success(
            api.get_route(route["id"], TEST_USERS["planner_headers"])
        )
        assert route_after["status"] == "PLANNED"


class TestStaleReturnGatedByStopDelivered:
    def test_stale_return_rejected_when_stop_pending(self, api):
        """PRD §3.8: "The referenced stop must be in the `DELIVERED` state,
        or the create is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/stale_return_gated_by_stop_delivered
        """
        ctx = setup_released_batch_scenario(plant_name="Plant Rho", order_qty=100)
        plant = ctx["plant"]
        store = ctx["store"]
        driver = ctx["driver"]
        order = ctx["order"]
        batch = ctx["batch"]

        route = create_route(plant["id"], driver["id"])
        stop = create_stop(route["id"], order["id"], 100, [batch["id"]])
        # Stop is still PENDING (route has not started loading).
        resp = api.create_stale_return(
            {"store_id": store["id"], "route_stop_id": stop["id"],
             "lines": [{"batch_id": batch["id"], "qty": 2}]},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_stale_return_accepted_after_delivery(self, api):
        """PRD §3.8: "At creation the return enters `PENDING_VERIFICATION`"
        — the positive leg once the stop has been DELIVERED.

        Design: Difficulty/cross_entity_state_dependency/stale_return_gated_by_stop_delivered
        """
        ctx = setup_delivered_stop_scenario(plant_name="Plant Rho 2", order_qty=100)
        store = ctx["store"]
        driver = ctx["driver"]
        stop = ctx["stop"]
        batch = ctx["batch"]

        set_clock("2026-08-10T15:00:00Z")
        sre = validate_success(
            api.create_stale_return(
                {"store_id": store["id"], "route_stop_id": stop["id"],
                 "lines": [{"batch_id": batch["id"], "qty": 2}]},
                make_driver_headers(driver["id"]),
            ),
            expected_status=201,
        )
        assert sre["status"] == "PENDING_VERIFICATION"
