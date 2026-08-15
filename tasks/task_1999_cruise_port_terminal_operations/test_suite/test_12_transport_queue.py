"""Ground transport: per-class FIFO discipline, the fifteen-minute dispatch
window capacity, and the single-requeue limit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_transport_slot,
    set_clock,
    setup_arrived_call,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["operator_headers"]


class TestFifoPerVehicleClass:
    def test_fifo_enforced_per_terminal_and_class(self, api):
        """PRD §3.9: "Each new slot is stamped with the next `queue_seq` — a
        monotone sequence maintained per terminal and vehicle class that fixes
        the first-in-first-out order — starts with `requeue_count` at 0,
        carries a null `dispatch_window_start` until it is dispatched, and
        begins life `QUEUED`."
        PRD §3.9: "strict FIFO — no other `QUEUED` slot of the same terminal
        and `vehicle_class` may hold a lower `queue_seq`, or the dispatch is
        rejected with `ERR_QUEUE_ORDER`"

        Design: Corner/validations/transport_fifo_per_vehicle_class
        """
        ctx = setup_arrived_call(taxi_dispatch_capacity_per_window=5)
        term = ctx["terminal"]["id"]
        pc = ctx["port_call"]["id"]

        t1 = create_transport_slot(term, pc, vehicle_class="TAXI", party_size=2)
        t2 = create_transport_slot(term, pc, vehicle_class="TAXI", party_size=3)
        s1 = create_transport_slot(term, pc, vehicle_class="SHUTTLE",
                                   party_size=8)
        assert t2["queue_seq"] == t1["queue_seq"] + 1, (
            "the class queue assigns the next sequence value"
        )

        # Dispatching the second TAXI while the first is QUEUED violates FIFO.
        err = api.dispatch_transport_slot(t2["id"], OPERATOR)
        validate_error(err, ApiErrorId.ERR_QUEUE_ORDER)

        # The SHUTTLE class queue is independent and empty ahead of S1.
        shut = validate_success(api.dispatch_transport_slot(s1["id"], OPERATOR))
        assert shut["status"] == "DISPATCHED"

        first = validate_success(api.dispatch_transport_slot(t1["id"], OPERATOR))
        assert first["status"] == "DISPATCHED"
        second = validate_success(api.dispatch_transport_slot(t2["id"], OPERATOR))
        assert second["status"] == "DISPATCHED"


class TestDispatchWindowCapacity:
    def test_fifteen_minute_window_capacity(self, api):
        """PRD §3.9: "The dispatch clock divides time into fifteen-minute
        windows aligned to quarter-hour boundaries, the current window being
        the one containing the logical now. A dispatch consumes one unit of its
        window's `taxi_dispatch_capacity_per_window` and keeps consuming it
        even after the slot completes or no-shows: the count that matters is
        the terminal's slots whose `dispatch_window_start` equals the current
        window's start and whose status is `DISPATCHED`, `COMPLETED`, or
        `NO_SHOW`."
        PRD §3.9: "When that count already equals the capacity, the next
        dispatch in the window is rejected with `ERR_QUEUE_WINDOW_FULL`;
        `QUEUED` and `EXPIRED` slots consume nothing. A successful dispatch
        stamps `dispatch_window_start` with the start of the current window."

        Design: Corner/validations/transport_window_capacity_15min
        """
        ctx = setup_arrived_call(taxi_dispatch_capacity_per_window=2)
        term = ctx["terminal"]["id"]
        pc = ctx["port_call"]["id"]

        set_clock("2026-08-10T10:07:00Z")
        t1 = create_transport_slot(term, pc, vehicle_class="TAXI")
        t2 = create_transport_slot(term, pc, vehicle_class="TAXI")
        t3 = create_transport_slot(term, pc, vehicle_class="TAXI")

        d1 = validate_success(api.dispatch_transport_slot(t1["id"], OPERATOR))
        assert_instant_equal(d1["dispatch_window_start"],
                             "2026-08-10T10:00:00Z",
                             label="dispatch window is floored to the quarter hour")
        validate_success(api.dispatch_transport_slot(t2["id"], OPERATOR))

        full = api.dispatch_transport_slot(t3["id"], OPERATOR)
        validate_error(full, ApiErrorId.ERR_QUEUE_WINDOW_FULL)

        # Completing T1 does not free its window slot.
        validate_success(api.complete_transport_slot(t1["id"], OPERATOR))
        still_full = api.dispatch_transport_slot(t3["id"], OPERATOR)
        validate_error(still_full, ApiErrorId.ERR_QUEUE_WINDOW_FULL)

        # Once the logical clock crosses into the next window, capacity opens.
        set_clock("2026-08-10T10:16:00Z")
        d3 = validate_success(api.dispatch_transport_slot(t3["id"], OPERATOR))
        assert d3["status"] == "DISPATCHED"
        assert_instant_equal(d3["dispatch_window_start"],
                             "2026-08-10T10:15:00Z")


class TestRequeueLimit:
    def test_second_requeue_rejected(self, api):
        """PRD §3.9: "A no-show party gets exactly one second chance:
        requeueing moves the slot `NO_SHOW` → `QUEUED`, increments
        `requeue_count` by 1, and assigns a fresh `queue_seq`, rejoining at the
        back of its class queue. A slot whose `requeue_count` has already
        reached 1 cannot be requeued again — the attempt is rejected with
        `ERR_REQUEUE_LIMIT`."

        Design: Corner/state_machines/transport_requeue_limit_second_requeue_rejected
        """
        ctx = setup_arrived_call(taxi_dispatch_capacity_per_window=5)
        term = ctx["terminal"]["id"]
        pc = ctx["port_call"]["id"]

        slot = create_transport_slot(term, pc, vehicle_class="TAXI")
        validate_success(api.dispatch_transport_slot(slot["id"], OPERATOR))
        validate_success(api.no_show_transport_slot(slot["id"], OPERATOR))

        requeued = validate_success(api.requeue_transport_slot(slot["id"], OPERATOR))
        assert requeued["status"] == "QUEUED"
        assert requeued["requeue_count"] == 1

        validate_success(api.dispatch_transport_slot(slot["id"], OPERATOR))
        validate_success(api.no_show_transport_slot(slot["id"], OPERATOR))

        err = api.requeue_transport_slot(slot["id"], OPERATOR)
        validate_error(err, ApiErrorId.ERR_REQUEUE_LIMIT)
