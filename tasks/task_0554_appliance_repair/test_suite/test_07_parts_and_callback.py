"""Second-trip depot orders, the ORDERED/BACKORDERED retry loop, and the callback cycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_parts_order,
    create_appointment_payload,
    setup_approved_request, second_trip_request, list_request_parts_orders,
    set_parts_order_status, book_appointment, complete_request, get_service_request,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _po_id(ctx):
    pos = list_request_parts_orders(ctx)
    assert pos, "second-trip must have created a depot parts order"
    return pos[0]["id"]


# ─── Difficulty: service_request_second_trip_callback_cycle ────────────────
def test_callback_visit_completes_request(api):
    """PRD §3.6: "Completion can occur two ways: directly from `APPROVED` on the same visit,
    transitioning `APPROVED → COMPLETED`; or from `SCHEDULED` on a callback visit, transitioning
    `SCHEDULED → COMPLETED`."
    PRD §3.5: "a dispatcher schedules the callback visit, driving the request
    `AWAITING_PARTS → SCHEDULED`".

    Design: Difficulty/non_linear_state_machine/service_request_second_trip_callback_cycle
    """
    ctx = setup_approved_request(model="M500")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    set_parts_order_status(_po_id(ctx), "RECEIVED")
    book_appointment(ctx, window_start="2026-06-12T09:00:00Z", window_end="2026-06-12T10:00:00Z")
    sr = complete_request(ctx, actual_labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    assert sr["status"] == "COMPLETED"


def test_visit_count_reaches_two_across_callback(api):
    """PRD §3.5: "A successful callback booking creates a new `BOOKED` appointment, sets
    `assigned_technician_id`, and increments `visit_count`, exactly as an initial booking does —
    this is the cyclic return into `SCHEDULED`."
    PRD §3.2: "The `visit_count` counts every `BOOKED` appointment ever created for the request
    across all visits."

    Design: Difficulty/non_linear_state_machine/service_request_second_trip_callback_cycle
    """
    ctx = setup_approved_request(model="M501")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    set_parts_order_status(_po_id(ctx), "RECEIVED")
    book_appointment(ctx, window_start="2026-06-12T09:00:00Z", window_end="2026-06-12T10:00:00Z")
    complete_request(ctx, actual_labor_tasks=[{"minutes": 40}, {"minutes": 20}])
    sr = get_service_request(ctx)
    assert sr["visit_count"] == 2


# ─── Difficulty: parts_order_backorder_retry_cycle ─────────────────────────
def test_parts_order_reaches_received_after_backorder_loop(api):
    """PRD §3.5: "`ORDERED → RECEIVED` when the part arrives, `ORDERED → BACKORDERED` when the
    depot cannot fill it yet, and `BACKORDERED → ORDERED` to retry — the order may loop between
    `ORDERED` and `BACKORDERED` any number of times before it is finally received."

    Design: Difficulty/non_linear_state_machine/parts_order_backorder_retry_cycle
    """
    ctx = setup_approved_request(model="M600")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    po_id = _po_id(ctx)
    set_parts_order_status(po_id, "BACKORDERED")
    set_parts_order_status(po_id, "ORDERED")
    po = set_parts_order_status(po_id, "RECEIVED")
    assert_parts_order(po)
    assert po["status"] == "RECEIVED"


def test_parts_order_backorder_and_reorder_intermediate_states(api):
    """PRD §3.5: "`ORDERED → BACKORDERED` when the depot cannot fill it yet, and
    `BACKORDERED → ORDERED` to retry — the order may loop between `ORDERED` and `BACKORDERED`
    any number of times before it is finally received."

    Design: Difficulty/non_linear_state_machine/parts_order_backorder_retry_cycle
    """
    ctx = setup_approved_request(model="M601")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    po_id = _po_id(ctx)
    backordered = set_parts_order_status(po_id, "BACKORDERED")
    assert backordered["status"] == "BACKORDERED"
    reordered = set_parts_order_status(po_id, "ORDERED")
    assert reordered["status"] == "ORDERED"


# ─── Difficulty: second_trip_appointment_cancel_cascade_depth3 (derivable core) ──
def test_second_trip_moves_request_to_awaiting_parts(api):
    """PRD §3.5: "From an `APPROVED` request, the assigned technician initiates a second trip by
    supplying a `part_id` and a `quantity`, driving the request `APPROVED → AWAITING_PARTS`."

    Design: Difficulty/transitive_cascade/second_trip_appointment_cancel_cascade_depth3
    """
    ctx = setup_approved_request(model="M800")
    sr = second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    assert sr["status"] == "AWAITING_PARTS"


def test_second_trip_creates_ordered_parts_order(api):
    """PRD §3.5: "The action creates a `PartsOrder` in `ORDERED` for the requested depot part
    and cancels the current `BOOKED` appointment".

    Design: Difficulty/transitive_cascade/second_trip_appointment_cancel_cascade_depth3
    """
    ctx = setup_approved_request(model="M801")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)
    pos = list_request_parts_orders(ctx)
    assert len(pos) == 1
    assert pos[0]["status"] == "ORDERED"


# ─── Corner: reschedule_before_parts_received_returns_parts_not_ready ──────
def test_reschedule_before_parts_received_rejected(api):
    """PRD §3.5: "This reschedule additionally requires that every `PartsOrder` for the request
    is `RECEIVED`; if any is not, the booking is rejected with `ERR_PARTS_NOT_READY`."

    Design: Corner/validations/reschedule_before_parts_received_returns_parts_not_ready
    """
    ctx = setup_approved_request(model="NC0")
    second_trip_request(ctx, part_id=ctx["part_id"], quantity=1)  # PartsOrder stays ORDERED
    res = api.create_appointment(
        ctx["sr_id"],
        create_appointment_payload(ctx["tech_id"], ctx["zone_id"],
                                   "2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z"),
        DISPATCHER)
    validate_error(res, ApiErrorId.ERR_PARTS_NOT_READY)
