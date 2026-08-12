"""Fleet dispatch: trip load gating, truck half-open windows, line buffer
windows, and cargo/compartment allocation rules (PRD §3.6, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_operator_headers,
    setup_confirmed_order, setup_completed_order, setup_medicated_mix_on_line,
    setup_batching_batch,
    make_employee, make_stocked_bin, make_line, make_batch, start_batch,
    record_weighment, mix_batch, collect_sample, enter_sample_result,
    release_batch, complete_order, make_truck, create_trip_payload,
    get_success_data,
)

MM = TEST_USERS["mill_manager_headers"]


class TestTripLoadGate:
    def _in_production_trip_setup(self, api):
        """Order 10t CONFIRMED with a batch started (order now IN_PRODUCTION)
        and a PLANNED trip already scheduled."""
        ctx = setup_batching_batch(tons=10, credit_limit_cents=1000000)
        truck = make_truck("TRK-01", "STANDARD_ONLY",
                           [{"compartment_seq": 1, "capacity_tons": 12}])
        trip = get_success_data(api.create_trip(
            create_trip_payload(truck["id"], ctx["order"]["id"]), MM))
        ctx["trip"] = trip
        return ctx

    def test_trip_load_rejected_while_order_in_production(self, api):
        """PRD §3.9: "Loading moves `PLANNED` → `LOADING` and requires the order to be `COMPLETED` (`ERR_INVALID_STATE`) and not `blocked` (`ERR_ORDER_BLOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/trip_load_requires_order_completed
        """
        ctx = self._in_production_trip_setup(api)
        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["status"] == "IN_PRODUCTION"

        resp = api.load_trip(ctx["trip"]["id"], MM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_trip_load_succeeds_after_order_completed(self, api):
        """PRD §3.9: "Loading moves `PLANNED` → `LOADING` and requires the order to be `COMPLETED` (`ERR_INVALID_STATE`) and not `blocked` (`ERR_ORDER_BLOCKED`)."

        Design: Difficulty/cross_entity_state_dependency/trip_load_requires_order_completed
        """
        ctx = self._in_production_trip_setup(api)
        # Finish production: weigh on target, mix, PASS sample, release, complete.
        record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                         ctx["bin_corn"]["id"], 7.000, ctx["op"]["id"])
        record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                         ctx["bin_sbm"]["id"], 3.000, ctx["op"]["id"])
        mix_batch(ctx["batch"]["id"], ctx["op"]["id"])
        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        enter_sample_result(sample["id"], ctx["qt"]["id"], 20.0, 4.0, 0)
        release_batch(ctx["batch"]["id"], ctx["qt"]["id"])
        order = complete_order(ctx["order"]["id"])
        assert order["status"] == "COMPLETED"

        loaded = validate_success(api.load_trip(ctx["trip"]["id"], MM), 200)
        assert loaded["status"] == "LOADING"


class TestTruckWindowHalfOpen:
    def _truck_with_first_trip(self, api):
        """16t order COMPLETED; truck with two 12t compartments; trip1
        occupies [09:00, 15:00) carrying 10t."""
        ctx = setup_completed_order(
            tons=16, target_tons=16, corn_actual=11.200, sbm_actual=4.800)
        truck = make_truck("TRK-02", "STANDARD_ONLY",
                           [{"compartment_seq": 1, "capacity_tons": 12},
                            {"compartment_seq": 2, "capacity_tons": 12}])
        trip1 = get_success_data(api.create_trip(
            create_trip_payload(
                truck["id"], ctx["order"]["id"],
                compartment_allocations=[{"compartment_seq": 1, "tons": 6,
                                          "cargo_class": "STANDARD"},
                                         {"compartment_seq": 2, "tons": 4,
                                          "cargo_class": "STANDARD"}],
                planned_departure_at="2026-05-03T09:00:00Z",
                planned_return_at="2026-05-03T15:00:00Z"), MM))
        ctx["truck"] = truck
        ctx["trip1"] = trip1
        return ctx

    def test_truck_back_to_back_departure_at_return_allowed(self, api):
        """PRD §3.9: "Back-to-back dispatch is expressly allowed: a new departure exactly at an existing return does not conflict."

        Design: Difficulty/resource_temporal_overlap/truck_trips_half_open_adjacency_allowed
        """
        ctx = self._truck_with_first_trip(api)
        # trip2 departs exactly at trip1's return: pure half-open adjacency.
        trip2 = validate_success(api.create_trip(
            create_trip_payload(
                ctx["truck"]["id"], ctx["order"]["id"],
                compartment_allocations=[{"compartment_seq": 1, "tons": 6,
                                          "cargo_class": "STANDARD"}],
                planned_departure_at="2026-05-03T15:00:00Z",
                planned_return_at="2026-05-03T18:00:00Z"), MM), 201)
        assert trip2["status"] == "PLANNED"
        # Tonnage note: 10 + 6 == order tons 16 — equality passes.
        assert trip2["total_tons"] == pytest.approx(6, abs=1e-6)

    def test_truck_departure_one_minute_before_return_conflicts(self, api):
        """PRD §3.9: "Trucks are shared resources under a pure half-open window rule with no buffer: trips of the same truck in `PLANNED`, `LOADING`, or `IN_TRANSIT` occupy their windows — `DELIVERED` and `CANCELLED` trips free the truck — and a new trip conflicts when its departure falls before an existing trip's return while that trip's departure falls before the new trip's return."
        PRD §3.9: "Violations are rejected with `ERR_TRUCK_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_trips_half_open_adjacency_allowed
        """
        ctx = self._truck_with_first_trip(api)
        # 14:59 < 15:00: the new window overlaps trip1's [09:00, 15:00).
        resp = api.create_trip(
            create_trip_payload(
                ctx["truck"]["id"], ctx["order"]["id"],
                compartment_allocations=[{"compartment_seq": 2, "tons": 1,
                                          "cargo_class": "STANDARD"}],
                planned_departure_at="2026-05-03T14:59:00Z",
                planned_return_at="2026-05-03T18:00:00Z"), MM)
        validate_error(resp, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT)


class TestLineWindowBuffer:
    def _line_with_first_batch(self, api):
        """10t CONFIRMED order; batch1 occupies [10:00, 11:00) on L1."""
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        line = make_line("L1")
        bat1 = make_batch(ctx["order"]["id"], line["id"], 5,
                          "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        ctx.update({"line": line, "bat1": bat1})
        return ctx

    def test_line_window_inside_cleanup_buffer_conflicts(self, api):
        """PRD §3.6: "every existing batch of the same line in `PLANNED`, `BATCHING`, `MIXED`, `HOLD`, `RELEASED`, or `REJECTED` occupies its planned window extended by a forty-five-minute cleanup buffer (a `CANCELLED` batch frees its window entirely)."
        PRD §3.6: "A colliding schedule is rejected with `ERR_LINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_batches_buffer_extended_adjacency_rejected
        """
        ctx = self._line_with_first_batch(api)
        # 11:30 < 11:00 + 45min: collides with the buffer-extended window even
        # though the raw [11:30, 12:30) window does not geometrically overlap.
        resp = api.create_batch({
            "order_id": ctx["order"]["id"], "line_id": ctx["line"]["id"],
            "target_tons": 5,
            "planned_start_at": "2026-05-02T11:30:00Z",
            "planned_end_at": "2026-05-02T12:30:00Z"}, MM)
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)

    def test_line_window_starting_exactly_at_buffer_end_allowed(self, api):
        """PRD §3.6: "the boundary is kind — a new start landing exactly at an existing window's buffer-extended end is allowed. A colliding schedule is rejected with `ERR_LINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_batches_buffer_extended_adjacency_rejected
        """
        ctx = self._line_with_first_batch(api)
        # 11:45 == batch1 end 11:00 + the forty-five-minute cleanup buffer.
        bat3 = validate_success(api.create_batch({
            "order_id": ctx["order"]["id"], "line_id": ctx["line"]["id"],
            "target_tons": 5,
            "planned_start_at": "2026-05-02T11:45:00Z",
            "planned_end_at": "2026-05-02T12:45:00Z"}, MM), 201)
        assert bat3["status"] == "PLANNED"


class TestTripCargoAndCapacity:
    def _medicated_completed_setup(self, api):
        """F-MED (med70/corn30) ACTIVE; permit-holding customer; medicated 1t
        order COMPLETED; a STANDARD_ONLY and a MEDICATED_CAPABLE truck."""
        ctx = setup_medicated_mix_on_line()
        # Finish the medicated batch: sample PASS (pinned floor 20.0), release,
        # complete. |1.000 - 1| / 1 = 0 <= 0.02.
        qt = make_employee("Quinn Quality", "QUALITY_TECH")
        sample = collect_sample(ctx["batch_med"]["id"], qt["id"])
        enter_sample_result(sample["id"], qt["id"], 25.0, 4.0, 0)
        release_batch(ctx["batch_med"]["id"], qt["id"])
        order = complete_order(ctx["order_med"]["id"])
        assert order["status"] == "COMPLETED"
        t_std = make_truck("T-STD", "STANDARD_ONLY",
                           [{"compartment_seq": 1, "capacity_tons": 12}])
        t_med = make_truck("T-MED", "MEDICATED_CAPABLE",
                           [{"compartment_seq": 1, "capacity_tons": 12}])
        ctx.update({"qt": qt, "order": order, "t_std": t_std, "t_med": t_med})
        return ctx

    def test_trip_cargo_and_capacity_errors(self, api):
        """PRD §3.9: "Every allocation's `cargo_class` must equal the order's medicated flag (`ERR_CARGO_CLASS_MIX`), and medicated cargo requires a `MEDICATED_CAPABLE` truck (`ERR_TRUCK_NOT_MEDICATED_CAPABLE`)."
        PRD §3.9: "Each allocation's `tons` must fit its compartment's `capacity_tons`, with equality passing (`ERR_COMPARTMENT_CAPACITY_EXCEEDED`) — a check always evaluated before the order-level rule that the sum of `total_tons` across the order's non-`CANCELLED` trips must not exceed the order's `tons`, again with equality passing (`ERR_ORDER_TONNAGE_OVERALLOCATED`)."

        Design: Corner/errors/trip_cargo_and_capacity_errors
        """
        ctx = self._medicated_completed_setup(api)
        order_id = ctx["order"]["id"]

        def trip_payload(truck_id, tons, cargo_class):
            return create_trip_payload(
                truck_id, order_id,
                compartment_allocations=[{"compartment_seq": 1, "tons": tons,
                                          "cargo_class": cargo_class}],
                planned_departure_at="2026-05-03T09:00:00Z",
                planned_return_at="2026-05-03T12:00:00Z")

        # Medicated cargo on a STANDARD_ONLY truck.
        r1 = api.create_trip(trip_payload(ctx["t_std"]["id"], 1, "MEDICATED"), MM)
        validate_error(r1, ApiErrorId.ERR_TRUCK_NOT_MEDICATED_CAPABLE)

        # STANDARD entry on a medicated order.
        r2 = api.create_trip(trip_payload(ctx["t_med"]["id"], 1, "STANDARD"), MM)
        validate_error(r2, ApiErrorId.ERR_CARGO_CLASS_MIX)

        # 99t into a 12t compartment.
        r3 = api.create_trip(trip_payload(ctx["t_med"]["id"], 99, "MEDICATED"), MM)
        validate_error(r3, ApiErrorId.ERR_COMPARTMENT_CAPACITY_EXCEEDED)

        # 2t allocated against a 1t order.
        r4 = api.create_trip(trip_payload(ctx["t_med"]["id"], 2, "MEDICATED"), MM)
        validate_error(r4, ApiErrorId.ERR_ORDER_TONNAGE_OVERALLOCATED)

        # The compliant allocation succeeds; equality on tonnage passes.
        trip = validate_success(
            api.create_trip(trip_payload(ctx["t_med"]["id"], 1, "MEDICATED"), MM), 201)
        assert trip["status"] == "PLANNED"
        assert trip["total_tons"] == pytest.approx(1, abs=1e-6)
