"""Dispatch and scheduling: plant batch-interval conflicts, truck turnaround,
the idle-time truck selector, capacity / short-load / availability guards, and
order-cancel blocking while loads are active."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    batch_load,
    create_truck,
    get_load,
    get_order,
    get_truck,
    place_order,
    schedule_load,
    schedule_load_fresh,
    set_clock,
    setup_batched_load,
    setup_completed_load,
    setup_confirmed_order,
    setup_standard_catalog,
    validate_error,
    validate_success,
    confirm_order,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BATCH_OP = TEST_USERS["batch_operator_headers"]
DRV1 = TEST_USERS["driver_headers"]


class TestPlantBatchInterval:
    def _three_load_order(self, api):
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 24.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2", "T3"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"]
        )
        l3 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=8.0, truck_id=ctx["trucks"]["T3"]["id"]
        )
        return ctx, l1, l2, l3

    def test_overlapping_batch_interval_rejected(self, api):
        """PRD §2.5: "No two loads on the same plant whose status is one of
        `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING` may have overlapping
        batch intervals; because the interval is half-open, one load's
        interval may begin exactly when another's ends — adjacency is allowed.
        A violating batch request is rejected with `ERR_PLANT_BATCH_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/plant_batch_interval_half_open_adjacency
        """
        ctx, l1, l2, l3 = self._three_load_order(api)
        batch_load(l1["id"], "2026-08-17T10:00:00Z")  # occupies [10:00, 10:30)

        res = api.batch_load(l2["id"], {"batch_time": "2026-08-17T10:15:00Z"}, BATCH_OP)
        validate_error(res, ApiErrorId.ERR_PLANT_BATCH_CONFLICT.value)
        assert get_load(l2["id"])["status"] == "SCHEDULED"

    def test_adjacent_batch_at_interval_end_accepted(self, api):
        """PRD §2.5: "The `batch_cycle_minutes` value defines the half-open
        batch interval occupied by any batched load: the interval runs from the
        load's `batch_time` up to but not including `batch_time` plus
        `batch_cycle_minutes`."
        PRD §2.5: "because the interval is half-open, one load's interval may
        begin exactly when another's ends — adjacency is allowed."

        Design: Difficulty/resource_temporal_overlap/plant_batch_interval_half_open_adjacency
        """
        ctx, l1, l2, l3 = self._three_load_order(api)
        batch_load(l1["id"], "2026-08-17T10:00:00Z")  # occupies [10:00, 10:30)

        res = api.batch_load(l3["id"], {"batch_time": "2026-08-17T10:30:00Z"}, BATCH_OP)
        batched = validate_success(res, 200)
        assert batched["status"] == "BATCHED", (
            "10:30 is exactly the end of [10:00, 10:30) — adjacency allowed"
        )


class TestTruckTurnaround:
    def _reuse_truck_order(self, api):
        """One order whose first 8.0 load on T1 batched at 10:00 and completed
        at 11:00, and a second load again manually assigned to T1."""
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "14:00",
            },
            truck_fleet_numbers=("T1",),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        batch_load(l1["id"], "2026-08-17T10:00:00Z")
        validate_success(api.depart_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T10:20:00Z")
        validate_success(api.arrive_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T11:00:00Z")
        validate_success(
            api.complete_load(l1["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        l2 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"]
        )
        return ctx, l1, l2

    def test_batch_inside_90_minute_turnaround_rejected(self, api):
        """PRD §2.5: "A truck's `batch_time` for a new load must be at least
        90 minutes after the latest `batch_time` among that truck's
        non-cancelled loads. This is a closed interval: a batch exactly 90
        minutes after the previous one is allowed. A violation is rejected
        with `ERR_TRUCK_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/truck_turnaround_closed_buffer
        """
        ctx, l1, l2 = self._reuse_truck_order(api)
        res = api.batch_load(l2["id"], {"batch_time": "2026-08-17T11:15:00Z"}, BATCH_OP)
        validate_error(res, ApiErrorId.ERR_TRUCK_OVERLAP.value)
        assert get_load(l2["id"])["status"] == "SCHEDULED"

    def test_batch_exactly_90_minutes_after_accepted(self, api):
        """PRD §2.5: "This is a closed interval: a batch exactly 90 minutes
        after the previous one is allowed."

        Design: Difficulty/resource_temporal_overlap/truck_turnaround_closed_buffer
        """
        ctx, l1, l2 = self._reuse_truck_order(api)
        res = api.batch_load(l2["id"], {"batch_time": "2026-08-17T11:30:00Z"}, BATCH_OP)
        batched = validate_success(res, 200)
        assert batched["status"] == "BATCHED", (
            "11:30 is exactly 10:00 + 90 minutes — closed interval, equality allowed"
        )
        truck = get_truck(ctx["trucks"]["T1"]["id"])
        assert truck["status"] == "ON_DELIVERY"


class TestTruckSelector:
    def test_empty_candidate_set_rejected(self, api):
        """PRD §3.4: "Candidates are trucks of the order's plant that are
        `AVAILABLE` and whose `capacity_yd3` is at least the requested
        `qty_yd3`. Candidates are ranked by `last_available_at` ascending —
        longest-idle first — with ties broken by `created_at` ascending.
        `last_available_at` is stamped from the logical clock at truck
        creation, so it is never null. An empty candidate set is rejected with
        `ERR_NO_TRUCK_AVAILABLE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/zero_eligible_trucks_empty_selector
        """
        catalog = setup_standard_catalog()
        t1 = create_truck(catalog["plant"]["id"], fleet_number="T1", capacity_yd3=10.0)
        create_truck(catalog["plant"]["id"], fleet_number="T2", capacity_yd3=6.0)
        validate_success(api.truck_out_of_service(t1["id"], DISP), 200)
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            pour_date="2026-08-17",
        )
        confirmed = confirm_order(order["id"])

        res = api.schedule_load(
            confirmed["id"],
            {"qty_yd3": 8.0, "expected_order_version": confirmed["version"]},
            DISP,
        )
        validate_error(res, ApiErrorId.ERR_NO_TRUCK_AVAILABLE.value)

        after = get_order(confirmed["id"])
        assert after["delivery_status"] == "CONFIRMED"
        assert after["version"] == confirmed["version"], (
            "a rejected schedule must not bump the order version"
        )

    def test_exact_capacity_truck_is_eligible(self, api):
        """PRD §3.4: "Candidates are trucks of the order's plant that are
        `AVAILABLE` and whose `capacity_yd3` is at least the requested
        `qty_yd3`. Candidates are ranked by `last_available_at` ascending —
        longest-idle first — with ties broken by `created_at` ascending."

        Design: Difficulty/boundary_precision_check/zero_eligible_trucks_empty_selector
        """
        catalog = setup_standard_catalog()
        # One AVAILABLE truck with capacity exactly equal to the request.
        t1 = create_truck(catalog["plant"]["id"], fleet_number="T1", capacity_yd3=8.0)
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            pour_date="2026-08-17",
        )
        confirmed = confirm_order(order["id"])
        load = schedule_load(
            confirmed["id"], confirmed["version"], qty_yd3=8.0
        )
        assert load["status"] == "SCHEDULED"
        assert load["truck_id"] == t1["id"], (
            "capacity 8.0 >= requested 8.0 keeps the candidate set non-empty"
        )

    def test_longest_idle_truck_selected_with_created_at_tiebreak(self, api):
        """PRD §3.4: "Candidates are ranked by `last_available_at` ascending —
        longest-idle first — with ties broken by `created_at` ascending."

        Design: Corner/calculations/truck_selector_longest_idle_then_created_at
        """
        catalog = setup_standard_catalog()
        # T1 idles from 00:00, T2 from 00:01, T3 from 00:02.
        t1 = create_truck(catalog["plant"]["id"], fleet_number="T1", capacity_yd3=10.0)
        set_clock("2026-08-01T00:01:00Z")
        t2 = create_truck(catalog["plant"]["id"], fleet_number="T2", capacity_yd3=10.0)
        set_clock("2026-08-01T00:02:00Z")
        t3 = create_truck(catalog["plant"]["id"], fleet_number="T3", capacity_yd3=10.0)

        # Order A burns T1 and frees it again at 2026-08-15T12:00.
        order_a = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirmed_a = confirm_order(order_a["id"])
        la = schedule_load(
            confirmed_a["id"], confirmed_a["version"], qty_yd3=8.0, truck_id=t1["id"]
        )
        batch_load(la["id"], "2026-08-15T10:00:00Z")
        validate_success(api.depart_load(la["id"], DRV1), 200)
        set_clock("2026-08-15T10:30:00Z")
        validate_success(api.arrive_load(la["id"], DRV1), 200)
        set_clock("2026-08-15T12:00:00Z")
        validate_success(
            api.complete_load(la["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )

        # Order B schedules with truck_id omitted -> selector runs.
        order_b = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            pour_date="2026-08-16",
        )
        confirmed_b = confirm_order(order_b["id"])
        lb = schedule_load(confirmed_b["id"], confirmed_b["version"], qty_yd3=8.0)
        assert lb["truck_id"] == t2["id"], (
            "T2 idle since 2026-08-01T00:01 beats T3 (00:02) and the "
            "just-freed T1 (2026-08-15T12:00)"
        )
        assert lb["status"] == "SCHEDULED"


class TestScheduleGuards:
    def test_load_exceeding_truck_capacity_rejected(self, api):
        """PRD §3.4: "The load's `qty_yd3` must not exceed the truck's
        `capacity_yd3`, otherwise `ERR_TRUCK_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/truck_capacity_exceeded_rejected
        """
        catalog = setup_standard_catalog()
        t2 = create_truck(catalog["plant"]["id"], fleet_number="T2", capacity_yd3=6.0)
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"],
            pour_date="2026-08-17",
        )
        confirmed = confirm_order(order["id"])
        res = api.schedule_load(
            confirmed["id"],
            {
                "qty_yd3": 8.0,
                "expected_order_version": confirmed["version"],
                "truck_id": t2["id"],
            },
            DISP,
        )
        validate_error(res, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED.value)

    def test_manual_assign_out_of_service_truck_rejected(self, api):
        """PRD §3.4: "If a `truck_id` is given, that truck must currently be
        `AVAILABLE`, otherwise `ERR_TRUCK_NOT_AVAILABLE` (HTTP 409)."

        Design: Corner/validations/manual_assign_out_of_service_truck_rejected
        """
        ctx = setup_confirmed_order(order_overrides={"pour_date": "2026-08-17"})
        t1 = ctx["trucks"]["T1"]
        validate_success(api.truck_out_of_service(t1["id"], DISP), 200)

        res = api.schedule_load(
            ctx["order"]["id"],
            {
                "qty_yd3": 8.0,
                "expected_order_version": ctx["order_version"],
                "truck_id": t1["id"],
            },
            DISP,
        )
        validate_error(res, ApiErrorId.ERR_TRUCK_NOT_AVAILABLE.value)

    def test_short_load_forbidden_when_customer_disallows(self, api):
        """PRD §3.4: "If the load's `qty_yd3` is below the pinned price list's
        `min_load_yd3` and the customer's `short_load_allowed` is false, the
        schedule is rejected with `ERR_SHORT_LOAD_FORBIDDEN` (HTTP 422); when
        `short_load_allowed` is true, such a load schedules fine and will
        simply incur the short-load fee at completion."

        Design: Corner/validations/short_load_forbidden_for_customer_flag
        """
        ctx = setup_confirmed_order(
            customer_overrides={"name": "Cust B", "short_load_allowed": False},
            order_overrides={
                "qty_yd3": 3.0,
                "pour_date": "2026-08-17",
            },
        )
        res = api.schedule_load(
            ctx["order"]["id"],
            {
                "qty_yd3": 3.0,
                "expected_order_version": ctx["order_version"],
                "truck_id": ctx["trucks"]["T1"]["id"],
            },
            DISP,
        )
        validate_error(res, ApiErrorId.ERR_SHORT_LOAD_FORBIDDEN.value)
        after = get_order(ctx["order"]["id"])
        assert after["version"] == ctx["order_version"], (
            "a rejected schedule must not bump the order version"
        )


class TestOrderCancelBlockedByActiveLoads:
    def test_cancel_with_batched_load_rejected(self, api):
        """PRD §3.3: "Cancelling from `CONFIRMED`, `SCHEDULED`, or
        `IN_PROGRESS` is blocked while any load of the order sits in
        `SCHEDULED`, `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING` — the
        rejection is `ERR_ORDER_HAS_ACTIVE_LOADS` (HTTP 409)."

        Design: Corner/validations/order_cancel_blocked_with_active_load
        """
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-15",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"]
        )
        batch_load(l1["id"], "2026-08-15T10:00:00Z")

        res = api.cancel_order(ctx["order"]["id"], DISP)
        validate_error(res, ApiErrorId.ERR_ORDER_HAS_ACTIVE_LOADS.value)
        order = get_order(ctx["order"]["id"])
        assert order["delivery_status"] == "IN_PROGRESS"

    def test_cancel_succeeds_once_remaining_load_cancelled(self, api):
        """PRD §3.3: "Cancelling from `CONFIRMED`, `SCHEDULED`, or
        `IN_PROGRESS` is blocked while any load of the order sits in
        `SCHEDULED`, `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING` — the
        rejection is `ERR_ORDER_HAS_ACTIVE_LOADS` (HTTP 409)."
        PRD §3.4: "A scheduled load can be cancelled by a `Dispatcher` while
        still in `SCHEDULED`, moving it to `CANCELLED`."

        Design: Corner/validations/order_cancel_blocked_with_active_load
        """
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-15",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T2",),
        )
        l2 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"],
        )

        # With a SCHEDULED load the cancel is blocked...
        res = api.cancel_order(ctx["order"]["id"], DISP)
        validate_error(res, ApiErrorId.ERR_ORDER_HAS_ACTIVE_LOADS.value)

        # ...until the load itself is cancelled from SCHEDULED.
        cancelled_load = validate_success(api.cancel_load(l2["id"], DISP), 200)
        assert cancelled_load["status"] == "CANCELLED"

        cancelled_order = validate_success(api.cancel_order(ctx["order"]["id"], DISP), 200)
        assert cancelled_order["delivery_status"] == "CANCELLED"
        assert cancelled_order["billing_status"] == "VOID"


class TestLoadStateErrors:
    def test_complete_from_scheduled_rejected(self, api):
        """PRD §3.7: "Completing a load from `ON_SITE` or `POURING` requires
        full discharge: the supplied `discharged_qty_yd3` must equal the load's
        batched `qty_yd3` exactly, otherwise `ERR_VOLUME_NOT_CONSERVED`
        (HTTP 422); a partial discharge must go through the return flow
        instead."
        PRD §2.8: "State-level checks follow: the optimistic-concurrency check
        (`ERR_STALE_VERSION`), the from-state validity check
        (`ERR_INVALID_STATE`), and the terminal-state check
        (`ERR_ALREADY_TERMINAL`)."

        Design: Corner/state_machines/complete_from_scheduled_rejected
        """
        ctx = setup_confirmed_order()
        load = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        res = api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_load(load["id"])
        assert after["status"] == "SCHEDULED"
        assert after["final_charge_cents"] is None
        assert after["concrete_cents"] is None

    def test_washout_from_batched_rejected(self, api):
        """PRD §3.7: "Washout is a `BatchOperator` action on the returned
        load: the load moves `RETURNED → WASHED_OUT`, the supplied
        `washout_water_gal` is recorded onto the return record (null until
        then), and the truck returns `IN_WASHOUT → AVAILABLE` with
        `last_available_at` stamped."

        Design: Corner/state_machines/washout_from_batched_rejected
        """
        ctx, load = setup_batched_load()
        res = api.washout_load(load["id"], {"washout_water_gal": 100}, BATCH_OP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        assert get_load(load["id"])["status"] == "BATCHED"
        records = validate_success(api.get_return_record(load["id"], DISP), 200)
        assert records == [], "no return record exists for a never-returned load"
