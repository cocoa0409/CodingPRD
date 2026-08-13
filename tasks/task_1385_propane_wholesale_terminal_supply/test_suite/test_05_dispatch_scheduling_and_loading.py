"""Dispatch: scheduling gates (truck availability, home terminal, capacity,
driver hours, buffered windows, rack bays, contract window), unschedule
reversals, the load-time reserve-floor safety gate, and cancel lockdown."""
from test_helpers import (
    DISPATCHER,
    SUPPLY_PLANNER,
    ApiErrorId,
    api_client,
    assert_delivery_order,
    base_order_fixture,
    create_order,
    create_terminal,
    create_truck,
    dealer_with_active_contract,
    get_success_data,
    make_dealer_user_headers,
    schedule_order,
    set_clock,
    unschedule_order,
    validate_error,
    validate_success,
)


def _schedule_attempt(order_id, truck_id, start, end):
    return api_client.schedule_delivery_order(
        order_id,
        {"truck_id": truck_id, "planned_load_start": start,
         "planned_load_end": end},
        DISPATCHER,
    )


class TestScheduleUnscheduleLoop:

    def _setup_allocated(self):
        ctx = base_order_fixture(name="T-S3", truck_count=2)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        return ctx, order

    def test_unschedule_reverts_to_allocated_and_releases(self):
        """PRD section 3.6: "Unscheduling reverses this: the order returns from
        `SCHEDULED` to `ALLOCATED`, `truck_id` and `est_trip_minutes` are
        cleared, and the committed hours and window occupancy are released."

        Design: Difficulty/non_linear_state_machine/order_schedule_unschedule_revert_loop
        """
        ctx, order = self._setup_allocated()
        t1, t2 = ctx["trucks"]
        schedule_order(order["id"], t1["id"], "2026-08-03T08:00:00Z",
                       "2026-08-03T10:00:00Z")
        unschedule_order(order["id"])

        mid = get_success_data(api_client.get_delivery_order(order["id"],
                                                             DISPATCHER))
        assert mid["fulfillment_status"] == "ALLOCATED"
        assert mid["truck_id"] is None
        assert mid["est_trip_minutes"] is None

        truck_after = get_success_data(api_client.get_truck(t1["id"],
                                                            DISPATCHER))
        assert truck_after["weekly_committed_minutes"] == 0, (
            "unscheduling releases the 330 committed minutes; got "
            f"{truck_after['weekly_committed_minutes']}")

    def test_reschedule_on_different_truck_succeeds(self):
        """PRD section 3.6: "Unscheduling reverses this: the order returns from
        `SCHEDULED` to `ALLOCATED`, `truck_id` and `est_trip_minutes` are
        cleared, and the committed hours and window occupancy are released." —
        the revert is a legal midpoint, so the loop may run again.
        PRD section 3.6: "Scheduling is the `Dispatcher`'s act of placing an
        `ALLOCATED` order onto a truck and a rack window"

        Design: Difficulty/non_linear_state_machine/order_schedule_unschedule_revert_loop
        """
        ctx, order = self._setup_allocated()
        t1, t2 = ctx["trucks"]
        schedule_order(order["id"], t1["id"], "2026-08-03T08:00:00Z",
                       "2026-08-03T10:00:00Z")
        unschedule_order(order["id"])
        resp = _schedule_attempt(order["id"], t2["id"], "2026-08-04T08:00:00Z",
                                 "2026-08-04T10:00:00Z")
        done = validate_success(resp, expected_status=200)
        assert_delivery_order(done)
        assert done["fulfillment_status"] == "SCHEDULED"
        assert done["truck_id"] == t2["id"], \
            "the second iteration of the loop binds the other truck"


class TestScheduleConservation:

    def _setup_allocated_monday(self):
        """Clock pinned to Monday 2026-08-03 so the load window falls inside
        the current ISO week (weekly_committed_minutes is computed over the
        week containing the logical clock's current instant)."""
        ctx = base_order_fixture(name="T-I1", clock="2026-08-03T00:00:00Z")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        return ctx, order

    def test_schedule_unschedule_conserves_truck_minutes(self):
        """PRD section 3.6: "the trip estimate is 90 minutes of rack service
        time plus twice the zone's `one_way_drive_minutes`"
        PRD section 3.6: "Unscheduling reverses this: the order returns from
        `SCHEDULED` to `ALLOCATED`, `truck_id` and `est_trip_minutes` are
        cleared, and the committed hours and window occupancy are released."

        Design: Difficulty/compensating_invariant/schedule_unschedule_conserves_truck_minutes_and_reserved
        """
        ctx, order = self._setup_allocated_monday()
        truck = ctx["trucks"][0]
        before = get_success_data(api_client.get_truck(truck["id"], DISPATCHER))
        assert before["weekly_committed_minutes"] == 0

        scheduled = schedule_order(order["id"], truck["id"],
                                   "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        # 90 rack-service minutes + 2 * 120 one-way minutes.
        assert scheduled["est_trip_minutes"] == 330
        during = get_success_data(api_client.get_truck(truck["id"], DISPATCHER))
        assert during["weekly_committed_minutes"] == 330, (
            f"scheduling adds exactly est_trip_minutes; got "
            f"{during['weekly_committed_minutes']}")

        unschedule_order(order["id"])
        after = get_success_data(api_client.get_truck(truck["id"], DISPATCHER))
        assert after["weekly_committed_minutes"] == 0, \
            "the compensating unschedule subtracts exactly the same amount"

    def test_schedule_unschedule_keeps_reserved_gallons(self):
        """PRD section 2.8: "Gallons promised but not yet loaded are tracked by
        `reserved_gal`, the sum of `allocated_gal` over the terminal's orders
        in `ALLOCATED` or `SCHEDULED`; requests and shorted orders hold
        nothing."

        Design: Difficulty/compensating_invariant/schedule_unschedule_conserves_truck_minutes_and_reserved
        """
        ctx, order = self._setup_allocated_monday()
        term_id = ctx["terminal"]["id"]

        def reserved():
            return get_success_data(api_client.get_inventory_summary(
                term_id, SUPPLY_PLANNER))["reserved_gal"]

        assert reserved() == 9_000
        schedule_order(order["id"], ctx["trucks"][0]["id"],
                       "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        assert reserved() == 9_000, "ALLOCATED and SCHEDULED both reserve"
        unschedule_order(order["id"])
        assert reserved() == 9_000, \
            "the reservation survives the schedule/unschedule loop"


class TestTruckStateGates:

    def _setup_allocated_with_truck(self):
        ctx = base_order_fixture(name="T-X3")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        return ctx, order

    def test_order_schedule_requires_truck_available(self):
        """PRD section 3.6: "The truck must be `AVAILABLE`
        (`ERR_TRUCK_NOT_AVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/order_schedule_requires_truck_available
        """
        ctx, order = self._setup_allocated_with_truck()
        truck = ctx["trucks"][0]
        api_client.transition_truck(truck["id"], {"to_state": "OUT_OF_SERVICE"},
                                    DISPATCHER)

        resp = _schedule_attempt(order["id"], truck["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TRUCK_NOT_AVAILABLE)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
        assert after["fulfillment_status"] == "ALLOCATED"
        assert after["truck_id"] is None

    def test_order_schedule_after_truck_returns_to_service(self):
        """PRD section 3.1: "Returning the truck to `AVAILABLE` makes it
        schedulable again."

        Design: Difficulty/cross_entity_state_dependency/order_schedule_requires_truck_available
        """
        ctx, order = self._setup_allocated_with_truck()
        truck = ctx["trucks"][0]
        api_client.transition_truck(truck["id"], {"to_state": "OUT_OF_SERVICE"},
                                    DISPATCHER)
        api_client.transition_truck(truck["id"], {"to_state": "AVAILABLE"},
                                    DISPATCHER)

        resp = _schedule_attempt(order["id"], truck["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        done = validate_success(resp, expected_status=200)
        assert done["fulfillment_status"] == "SCHEDULED"
        assert done["truck_id"] == truck["id"]

    def test_truck_out_of_service_unschedules_orders(self):
        """PRD section 3.1: "While a truck is `OUT_OF_SERVICE`, it cannot take
        new schedules, and taking it out of service returns each of its
        `SCHEDULED` orders to `ALLOCATED` — `truck_id` and `est_trip_minutes`
        are cleared and the committed hours and rack occupancy are released."

        Design: Corner/state_machines/truck_out_of_service_unschedules_orders
        """
        ctx = base_order_fixture(name="T-M10", clock="2026-08-03T00:00:00Z")
        truck = ctx["trucks"][0]
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        schedule_order(order["id"], truck["id"], "2026-08-03T08:00:00Z",
                       "2026-08-03T10:00:00Z")

        resp = api_client.transition_truck(
            truck["id"], {"to_state": "OUT_OF_SERVICE"}, DISPATCHER)
        validate_success(resp, expected_status=200)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
        assert after["fulfillment_status"] == "ALLOCATED"
        assert after["truck_id"] is None
        assert after["est_trip_minutes"] is None

        truck_after = get_success_data(api_client.get_truck(truck["id"],
                                                            DISPATCHER))
        assert truck_after["weekly_committed_minutes"] == 0, \
            "the 330 committed minutes are released with the window"


class TestBufferedTruckWindows:

    def _setup_three_orders(self):
        ctx = base_order_fixture(name="T-T1")
        truck = ctx["trucks"][0]
        orders = [
            create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 9_000,
                         dealer_contract_id=ctx["dealer_contract"]["id"])
            for _ in range(3)
        ]
        schedule_order(orders[0]["id"], truck["id"], "2026-08-03T08:00:00Z",
                       "2026-08-03T10:00:00Z")
        return ctx, truck, orders

    def test_truck_window_overlap_with_deadhead_buffer(self):
        """PRD section 3.6: "The buffered truck window must not overlap any
        other order on the same truck in `SCHEDULED`, `LOADED`, or `DELIVERED`:
        each order occupies an interval from 60 minutes before its
        `planned_load_start` to 60 minutes after its `planned_load_end`,
        half-open, and two occupied intervals conflict when the later start
        falls strictly before the earlier end — exact back-to-back at the
        buffer boundary is fine, one minute of intersection is a conflict
        rejected with `ERR_TRUCK_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_window_overlap_with_deadhead_buffer
        """
        ctx, truck, orders = self._setup_three_orders()
        # o1 occupies [07:00, 11:00). o2's [11:00, 15:00) touches it exactly
        # at 11:00: half-open boundary is not a conflict.
        resp = _schedule_attempt(orders[1]["id"], truck["id"],
                                 "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
        done = validate_success(resp, expected_status=200)
        assert done["fulfillment_status"] == "SCHEDULED"

        # o3 occupies [12:30, 16:30), intersecting o2's [11:00, 15:00).
        resp = _schedule_attempt(orders[2]["id"], truck["id"],
                                 "2026-08-03T13:30:00Z", "2026-08-03T15:30:00Z")
        validate_error(resp, ApiErrorId.ERR_TRUCK_SCHEDULE_CONFLICT)

    def test_one_minute_into_buffer_conflicts(self):
        """PRD section 3.6: "exact back-to-back at the buffer boundary is fine,
        one minute of intersection is a conflict rejected with
        `ERR_TRUCK_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_window_overlap_with_deadhead_buffer
        """
        ctx, truck, orders = self._setup_three_orders()
        # [11:59, 13:59) occupies [10:59, 14:59): one minute into o1's
        # buffered [07:00, 11:00) — a conflict.
        resp = _schedule_attempt(orders[1]["id"], truck["id"],
                                 "2026-08-03T11:59:00Z", "2026-08-03T13:59:00Z")
        validate_error(resp, ApiErrorId.ERR_TRUCK_SCHEDULE_CONFLICT)


class TestRackBayCapacity:

    def _setup_three_trucks_orders(self, name="T-T2", rack_bays=2):
        ctx = base_order_fixture(name=name, rack_bay_count=rack_bays,
                                 truck_count=3)
        orders = [
            create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 9_000,
                         dealer_contract_id=ctx["dealer_contract"]["id"])
            for _ in range(3)
        ]
        return ctx, orders

    def test_rack_bay_aggregate_capacity(self):
        """PRD section 3.6: "The rack must have a bay: counting the terminal's
        orders in `SCHEDULED` or `LOADED` whose raw, unbuffered windows overlap
        the candidate's raw window, the schedule is rejected with
        `ERR_RACK_CAPACITY_EXCEEDED` when that count already equals
        `rack_bay_count` — so exactly `rack_bay_count` overlapping windows are
        permitted and the next one is refused."

        Design: Difficulty/resource_temporal_overlap/rack_bay_aggregate_capacity
        """
        ctx, orders = self._setup_three_trucks_orders()
        t1, t2, t3 = ctx["trucks"]
        # Two overlapping raw windows == rack_bay_count: both allowed.
        schedule_order(orders[0]["id"], t1["id"], "2026-08-04T08:00:00Z",
                       "2026-08-04T10:00:00Z")
        schedule_order(orders[1]["id"], t2["id"], "2026-08-04T08:00:00Z",
                       "2026-08-04T10:00:00Z")
        # The third overlapping raw window is refused.
        resp = _schedule_attempt(orders[2]["id"], t3["id"],
                                 "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_RACK_CAPACITY_EXCEEDED)

    def test_rack_bay_uses_raw_unbuffered_windows(self):
        """PRD section 3.6: "counting the terminal's orders in `SCHEDULED` or
        `LOADED` whose raw, unbuffered windows overlap the candidate's raw
        window" — the 60-minute deadhead buffer does not widen rack occupancy.

        Design: Difficulty/resource_temporal_overlap/rack_bay_aggregate_capacity
        """
        ctx, orders = self._setup_three_trucks_orders()
        t1, t2, t3 = ctx["trucks"]
        schedule_order(orders[0]["id"], t1["id"], "2026-08-04T08:00:00Z",
                       "2026-08-04T10:00:00Z")
        schedule_order(orders[1]["id"], t2["id"], "2026-08-04T08:00:00Z",
                       "2026-08-04T10:00:00Z")
        # Raw window [11:00, 13:00) overlaps neither booked window, so the bay
        # count is not reached even though buffered intervals would intersect.
        resp = _schedule_attempt(orders[2]["id"], t3["id"],
                                 "2026-08-04T11:00:00Z", "2026-08-04T13:00:00Z")
        done = validate_success(resp, expected_status=200)
        assert done["fulfillment_status"] == "SCHEDULED"


class TestDriverHours:

    def _setup_four_orders_zone555(self):
        """Zone with 555 one-way minutes -> est_trip 90 + 2*555 = 1200 min;
        truck weekly limit 3600 min; four 5000-gal ALLOCATED orders."""
        # Clock pinned to Monday 2026-08-03 so every load window below falls
        # inside the ISO week containing the clock's current instant.
        ctx = base_order_fixture(name="T-B3", rack_bay_count=4,
                                 zone_code="Z3", one_way_drive_minutes=555,
                                 clock="2026-08-03T00:00:00Z")
        truck = ctx["trucks"][0]
        orders = [
            create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 5_000,
                         dealer_contract_id=ctx["dealer_contract"]["id"])
            for _ in range(4)
        ]
        return ctx, truck, orders

    def test_driver_hours_exact_limit_allowed(self):
        """PRD section 3.6: "the truck's `weekly_committed_minutes` plus this
        candidate's `est_trip_minutes` must not exceed
        `weekly_hours_limit_minutes` — equality is allowed, one minute over is
        rejected with `ERR_DRIVER_HOURS_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/driver_hours_exact_limit_allowed
        """
        ctx, truck, orders = self._setup_four_orders_zone555()
        windows = [("2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z"),
                   ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
                   ("2026-08-03T16:00:00Z", "2026-08-03T18:00:00Z")]
        for order, (start, end) in zip(orders[:3], windows):
            done = schedule_order(order["id"], truck["id"], start, end)
            assert done["fulfillment_status"] == "SCHEDULED"
        # 3 * 1200 == 3600 == the weekly limit: equality is allowed.
        truck_after = get_success_data(api_client.get_truck(truck["id"],
                                                            DISPATCHER))
        assert truck_after["weekly_committed_minutes"] == 3_600

    def test_driver_hours_one_trip_over_rejected(self):
        """PRD section 3.6: "the truck's `weekly_committed_minutes` plus this
        candidate's `est_trip_minutes` must not exceed
        `weekly_hours_limit_minutes` — equality is allowed, one minute over is
        rejected with `ERR_DRIVER_HOURS_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/driver_hours_exact_limit_allowed
        """
        ctx, truck, orders = self._setup_four_orders_zone555()
        windows = [("2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z"),
                   ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
                   ("2026-08-03T16:00:00Z", "2026-08-03T18:00:00Z")]
        for order, (start, end) in zip(orders[:3], windows):
            schedule_order(order["id"], truck["id"], start, end)
        # 3600 + 1200 > 3600: one more trip this week is one trip too many.
        resp = _schedule_attempt(orders[3]["id"], truck["id"],
                                 "2026-08-03T20:00:00Z", "2026-08-03T22:00:00Z")
        validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED)

    def test_safety_beats_constraint_on_schedule(self):
        """PRD section 2.9: "Every request passes through validation layers in
        a fixed order, so that an earlier failure masks later ones
        deterministically." and "Ninth, safety rules: driver hours-of-service
        and the reserve-floor check at load." precede "Tenth, capacity,
        referential, temporal, and uniqueness constraints."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_schedule
        """
        ctx, truck, orders = self._setup_four_orders_zone555()
        windows = [("2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z"),
                   ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
                   ("2026-08-03T16:00:00Z", "2026-08-03T18:00:00Z")]
        for order, (start, end) in zip(orders[:3], windows):
            schedule_order(order["id"], truck["id"], start, end)
        # The fourth window BOTH overflows the hours budget (3600 + 1200 >
        # 3600) AND overlaps the first order's buffered window; the safety
        # layer is earlier, so the hours error masks the conflict error.
        resp = _schedule_attempt(orders[3]["id"], truck["id"],
                                 "2026-08-03T09:00:00Z", "2026-08-03T11:00:00Z")
        validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED)

    def test_driver_hours_reject_without_any_overlap(self):
        """PRD section 3.6: "one minute over is rejected with
        `ERR_DRIVER_HOURS_EXCEEDED`." — the safety rule fires on its own when
        no other rule is violated.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_schedule
        """
        ctx, truck, orders = self._setup_four_orders_zone555()
        windows = [("2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z"),
                   ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
                   ("2026-08-03T16:00:00Z", "2026-08-03T18:00:00Z")]
        for order, (start, end) in zip(orders[:3], windows):
            schedule_order(order["id"], truck["id"], start, end)
        # A disjoint window in the same ISO week isolates the hours failure.
        resp = _schedule_attempt(orders[3]["id"], truck["id"],
                                 "2026-08-03T20:00:00Z", "2026-08-03T22:00:00Z")
        validate_error(resp, ApiErrorId.ERR_DRIVER_HOURS_EXCEEDED)


class TestScheduleConstraintGates:

    def test_truck_capacity_boundary_exact_and_over(self):
        """PRD section 3.6: "The order's `allocated_gal` must not exceed the
        truck's `capacity_gal` (`ERR_TRUCK_CAPACITY_EXCEEDED`)."

        Design: Corner/validations/truck_capacity_boundary_exact_and_over
        """
        ctx = base_order_fixture(name="T-V8")
        truck = ctx["trucks"][0]
        exact = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 11_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        over = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                            ctx["zone"]["id"], 11_001,
                            dealer_contract_id=ctx["dealer_contract"]["id"])

        # 11000 == capacity: does not exceed, allowed.
        resp = _schedule_attempt(exact["id"], truck["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        done = validate_success(resp, expected_status=200)
        assert done["fulfillment_status"] == "SCHEDULED"

        # 11001 > 11000: rejected.
        resp = _schedule_attempt(over["id"], truck["id"],
                                 "2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED)

    def test_truck_terminal_mismatch_rejected(self):
        """PRD section 3.6: "The truck's home terminal must equal the order's
        terminal (`ERR_TRUCK_TERMINAL_MISMATCH`)."

        Design: Corner/validations/truck_terminal_mismatch_rejected
        """
        ctx = base_order_fixture(name="T-V15A")
        tb = create_terminal(name="T-V15B", region_code="MW",
                             storage_capacity_gal=500_000,
                             reserve_floor_gal=20_000,
                             winter_reserve_floor_gal=60_000, rack_bay_count=1)
        foreign_truck = create_truck(tb["id"], unit_number="U-B1")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])

        resp = _schedule_attempt(order["id"], foreign_truck["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_TRUCK_TERMINAL_MISMATCH)

    def test_schedule_window_inverted_rejected(self):
        """PRD section 3.6: "The window end must be strictly after the window
        start, else `ERR_WINDOW_INVALID`."

        Design: Corner/validations/schedule_window_inverted_rejected
        """
        ctx = base_order_fixture(name="T-V5")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        resp = _schedule_attempt(order["id"], ctx["trucks"][0]["id"],
                                 "2026-08-03T10:00:00Z", "2026-08-03T08:00:00Z")
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)

    def test_schedule_outside_contract_window_rejected(self):
        """PRD section 3.6: "Finally, if the order carries a contract, the
        contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the calendar
        date of `planned_load_start` must fall inside the contract window
        (`ERR_OUTSIDE_CONTRACT_WINDOW`)."

        Design: Corner/errors/schedule_outside_contract_window_rejected
        """
        ctx = base_order_fixture(name="T-R2")
        # Rebuild with a contract whose window ends 2026-08-31.
        dealer, contract = dealer_with_active_contract(
            ctx["terminal"]["id"], legal_name="Dealer R2",
            window_start="2026-08-01", window_end="2026-08-31")
        order = create_order(dealer["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 9_000,
                             dealer_contract_id=contract["id"])

        # 2026-09-05 is past the contract window end; the contract is still
        # ACTIVE (expiry is an epoch event), so the window rule decides.
        resp = _schedule_attempt(order["id"], ctx["trucks"][0]["id"],
                                 "2026-09-05T08:00:00Z", "2026-09-05T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_CONTRACT_WINDOW)


class TestLoadSafetyGate:

    def test_reserve_floor_breach_at_load_rejected(self):
        """PRD section 3.6: "A `Dispatcher` may load a `SCHEDULED` order only
        if, after drawing the order's gallons, the terminal still holds at
        least its effective reserve floor — that is, `on_hand_gal` minus
        `allocated_gal` must be at least `effective_reserve_floor_gal`,
        season-dependent per section 2.8 — or the load is rejected with
        `ERR_RESERVE_FLOOR_BREACH`."

        Design: Corner/validations/reserve_floor_breach_at_load_rejected
        """
        # 20000 gal must fit the truck's tank (PRD 3.6 capacity gate).
        ctx = base_order_fixture(name="T-V16", stock_gal=70_000,
                                 truck_capacity_gal=20_000)
        truck = ctx["trucks"][0]
        # Summer ATP is 70000 - 50000 = 20000; the order takes it exactly.
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 20_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        schedule_order(order["id"], truck["id"], "2026-12-02T08:00:00Z",
                       "2026-12-02T10:00:00Z")

        # The clock enters WINTER_DRAW: the floor rises 50000 -> 150000.
        set_clock("2026-12-01T00:00:00Z")
        resp = api_client.load_delivery_order(order["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_RESERVE_FLOOR_BREACH)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
        assert after["fulfillment_status"] == "SCHEDULED", \
            "a rejected load leaves the order SCHEDULED"
        term = get_success_data(api_client.get_terminal(ctx["terminal"]["id"],
                                                        SUPPLY_PLANNER))
        assert term["on_hand_gal"] == 70_000, \
            "70000 - 20000 = 50000 < the 150000 winter floor; nothing is drawn"


class TestIllegalTransitionsAndLockdown:

    def test_order_invalid_transition_deliver_from_allocated(self):
        """PRD section 3.6: "When a `Dispatcher` delivers a `LOADED` order,
        `fulfillment_status` becomes `DELIVERED`" — delivery is defined from
        `LOADED` only.
        PRD section 2.9: "Seventh, generic transition legality: the entity must
        be in a valid from-state for the requested action, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_invalid_transition_deliver_from_allocated
        """
        ctx = base_order_fixture(name="T-M3", truck_count=0)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 5_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        assert order["fulfillment_status"] == "ALLOCATED"

        resp = api_client.deliver_delivery_order(order["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
        assert after["fulfillment_status"] == "ALLOCATED"
        assert after["invoice_status"] == "NOT_READY", \
            "a rejected deliver never opens the invoice"

    def test_cancelled_order_terminal_lockdown(self):
        """PRD section 3.6: "Cancellation is available from `REQUESTED`,
        `ALLOCATED`, `SHORTED`, or `SCHEDULED` — never from `LOADED` or beyond,
        and never from `DELIVERED`."
        PRD section 3.6: "In every case the invoice dimension moves from
        `NOT_READY` to `VOID`."
        PRD section 2.9: "Seventh, generic transition legality: the entity must
        be in a valid from-state for the requested action, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        ctx = base_order_fixture(name="T-M5")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 5_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        resp = api_client.cancel_delivery_order(
            order["id"], make_dealer_user_headers(ctx["dealer"]["id"]))
        cancelled = validate_success(resp, expected_status=200)
        assert cancelled["fulfillment_status"] == "CANCELLED"

        # A second cancel: CANCELLED is not a legal from-state.
        resp = api_client.cancel_delivery_order(order["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # Scheduling a CANCELLED order: scheduling places an ALLOCATED order.
        resp = _schedule_attempt(order["id"], ctx["trucks"][0]["id"],
                                 "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_delivery_order(order["id"],
                                                               DISPATCHER))
        assert after["invoice_status"] == "VOID", \
            "pre-delivery cancellation voids the invoice dimension"


class TestAllocateCancelConservation:

    def test_allocation_drops_atp_by_allocated_gallons(self):
        """PRD section 2.8: "The terminal's `available_to_promise_gal` is
        `on_hand_gal` minus the effective reserve floor minus `reserved_gal`."
        and "`reserved_gal`, the sum of `allocated_gal` over the terminal's
        orders in `ALLOCATED` or `SCHEDULED`"

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_atp
        """
        ctx = base_order_fixture(name="T-I3", truck_count=0)
        term_id = ctx["terminal"]["id"]

        def atp():
            return get_success_data(api_client.get_inventory_summary(
                term_id, SUPPLY_PLANNER))["available_to_promise_gal"]

        assert atp() == 350_000, "400000 on hand - 50000 summer floor"
        create_order(ctx["dealer"]["id"], term_id, ctx["zone"]["id"], 10_000,
                     dealer_contract_id=ctx["dealer_contract"]["id"])
        assert atp() == 340_000, \
            "the direct allocation reserves exactly its allocated gallons"

    def test_cancel_restores_atp_exactly(self):
        """PRD section 3.6: "Cancelling an `ALLOCATED` order releases its
        reserved gallons."

        Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_atp
        """
        ctx = base_order_fixture(name="T-I3", truck_count=0)
        term_id = ctx["terminal"]["id"]

        def atp():
            return get_success_data(api_client.get_inventory_summary(
                term_id, SUPPLY_PLANNER))["available_to_promise_gal"]

        before = atp()
        order = create_order(ctx["dealer"]["id"], term_id, ctx["zone"]["id"],
                             10_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        assert atp() == before - 10_000
        resp = api_client.cancel_delivery_order(
            order["id"], make_dealer_user_headers(ctx["dealer"]["id"]))
        validate_success(resp, expected_status=200)
        assert atp() == before, \
            "allocate + cancel conserves available_to_promise_gal exactly"
