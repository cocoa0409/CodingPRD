"""Delivery scheduling — route/stop state machines, capacity ledger, shift-window
and overlap guards, validation-priority conflicts, OCC on the route, and the
stop-completion bubble-up that delivers the order.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, TEST_USERS,
    create_customer, create_sofa_product, create_draft_order, add_line, pay_in_full,
    confirm, create_route, book_stop, setup_confirmed_paid_order, deliver_order,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]
DD = TEST_USERS["dispatcher_headers"]


def _confirmed_order(api, customer_id, product_id, tier="THRESHOLD"):
    # Pin the clock to the route factory's default service_date (2026-03-01) so the
    # order's created_at-date-based earliest_schedulable_date (PRD §3.4) does not run
    # ahead of the route's 2026-03-01 service_date and trip the §3.8 lead-time gate
    # (ERR_LEAD_TIME_NOT_MET). Idempotent with the explicit pins tests already do.
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    order = create_draft_order(customer_id, delivery_tier=tier)
    add_line(order["id"], product_id)
    pay_in_full(order["id"])
    return confirm(order["id"])


# ─── Difficulty: stop dispatch requires LOCKED route ──────────────────────
def test_dispatch_on_open_route_rejected(api):
    """PRD 3.9: "dispatch requires the stop to be `BOOKED` and the route to be `LOCKED`,
    and dispatching against a route that is not locked is rejected with
    `ERR_ROUTE_NOT_LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/stop_dispatch_requires_route_locked_state
    """
    product = create_sofa_product()
    customer = create_customer()
    order = _confirmed_order(api, customer["id"], product["id"])
    route = create_route()
    stop = book_stop(route["id"], order["id"], route["version"])
    res = api.dispatch_delivery_stop(stop["id"], DD)  # route still OPEN
    validate_error(res, "ERR_ROUTE_NOT_LOCKED")


def test_dispatch_succeeds_after_route_locked(api):
    """PRD 3.9: "Once the route is locked, a `DeliveryDispatcher` dispatches a booked stop,
    moving it `BOOKED → DISPATCHED` ..."

    Second test for this instance: locking the route unblocks the dispatch.

    Design: Difficulty/cross_entity_state_dependency/stop_dispatch_requires_route_locked_state
    """
    product = create_sofa_product()
    customer = create_customer()
    order = _confirmed_order(api, customer["id"], product["id"])
    route = create_route()
    stop = book_stop(route["id"], order["id"], route["version"])
    get_success_data(api.lock_delivery_route(route["id"], DD))
    dispatched = validate_success(api.dispatch_delivery_stop(stop["id"], DD), 200)
    assert dispatched["status"] == "DISPATCHED"


# ─── Difficulty: stop complete delivers order (depth-2 cascade) ───────────
def test_stop_complete_delivers_order(api):
    """PRD 3.9: "Completing a dispatched stop moves it `DISPATCHED → COMPLETED` and is the
    event that delivers the order: it bubbles the order's `fulfillment_status` from
    `SCHEDULED` to `DELIVERED` ..."

    Design: Difficulty/transitive_cascade/stop_complete_delivers_order_then_stamps_line_depth2
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    product = create_sofa_product()
    customer = create_customer()
    order = _confirmed_order(api, customer["id"], product["id"])
    route = create_route()
    stop = book_stop(route["id"], order["id"], route["version"])
    get_success_data(api.lock_delivery_route(route["id"], DD))
    get_success_data(api.dispatch_delivery_stop(stop["id"], DD))
    completed = validate_success(api.complete_delivery_stop(stop["id"], DD), 200)
    assert completed["status"] == "COMPLETED"
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["fulfillment_status"] == "DELIVERED", "order bubbled SCHEDULED -> DELIVERED"


def test_booking_first_stop_schedules_order(api):
    """PRD 3.8: "because this is the first stop booked for the order — the order's
    `fulfillment_status` moves `CONFIRMED → SCHEDULED` ..."

    Second test for the depth-2 chain: the order reaches SCHEDULED before delivery,
    establishing the SCHEDULED -> DELIVERED edge that completion fires.

    Design: Difficulty/transitive_cascade/stop_complete_delivers_order_then_stamps_line_depth2
    """
    product = create_sofa_product()
    customer = create_customer()
    order = _confirmed_order(api, customer["id"], product["id"])
    route = create_route()
    book_stop(route["id"], order["id"], route["version"])
    scheduled = get_success_data(api.get_order(order["id"], SA))
    assert scheduled["fulfillment_status"] == "SCHEDULED"


# ─── SKIPPED instance: capacity_business_fiscal_beats_route_not_open_state ─
# Design queue A asks this instance to assert that a booking which is BOTH over capacity
# AND on a LOCKED (not-open) route returns ERR_ROUTE_CAPACITY_EXCEEDED (scaffold priority
# 17 < 18). PRD §3.8 lists the booking guards as an explicit sequence — "The route must be
# `OPEN`; booking on a route that is not open is rejected with `ERR_ROUTE_NOT_OPEN`" FIRST,
# and capacity LAST ("Finally, the booking must not push ... above ... `capacity_units`").
# A faithful PRD-only reader would therefore surface ERR_ROUTE_NOT_OPEN, not the capacity
# error, when both fail. PRD prose does not uniquely-derive the asserted capacity-wins
# outcome (error-precedence Silence pattern), so this instance is SKIPPED — both tests
# omitted, assertion not weakened. (The sibling lead_time-vs-capacity instance below IS
# uniquely derivable, because PRD prose checks lead-time before capacity, matching it.)


# ─── Difficulty: lead-time (temporal p16) beats capacity (fiscal p17) ─────
def test_lead_time_beats_capacity(api):
    """PRD 3.8: "The route's `service_date` must be on or after the order's
    `earliest_schedulable_date`, so that special-order lead time is honored; an earlier
    service date is rejected with `ERR_LEAD_TIME_NOT_MET`."
    PRD 3.8: "Finally, the booking must not push the route's `committed_units` plus this
    stop's `unit_load` above the route's `capacity_units`; exceeding capacity is rejected
    with `ERR_ROUTE_CAPACITY_EXCEEDED`."

    PRD §3.8 sequences the guards with lead-time before capacity (capacity is explicitly
    "Finally"), so a booking that fails BOTH surfaces ERR_LEAD_TIME_NOT_MET first.

    Design: Difficulty/priority_pair_validation_conflict/lead_time_temporal_beats_capacity_fiscal
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, SM))
    sofa = create_sofa_product()
    special = get_success_data(api.create_product({
        "sku": "MATT-SPECIAL", "name": "Custom Mattress", "category": "MATTRESS",
        "base_price_cents": 80000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "QUEEN", "surcharge_cents": 0}],
        "is_special_order": True, "lead_days": 14}, SM))
    customer = create_customer()
    route = create_route(capacity_units=1)  # service_date 2026-03-01
    order_a = _confirmed_order(api, customer["id"], sofa["id"])
    book_stop(route["id"], order_a["id"], route["version"])  # fills capacity
    order_b = create_draft_order(customer["id"])
    add_line(order_b["id"], special["id"], fabric_code="STANDARD", size_code="QUEEN")
    pay_in_full(order_b["id"])
    confirm(order_b["id"])  # earliest_schedulable_date 2026-03-15
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 700, "window_end_minute": 760,
        "expected_route_version": fresh["version"]}, DD)
    validate_error(res, "ERR_LEAD_TIME_NOT_MET")


def test_lead_time_not_met_alone_rejected(api):
    """PRD 3.8: "The route's `service_date` must be on or after the order's
    `earliest_schedulable_date`, so that special-order lead time is honored; an earlier
    service date is rejected with `ERR_LEAD_TIME_NOT_MET`."

    Second test for this instance: lead-time failure stands alone with ample capacity.

    Design: Difficulty/priority_pair_validation_conflict/lead_time_temporal_beats_capacity_fiscal
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, SM))
    special = get_success_data(api.create_product({
        "sku": "MATT-SPECIAL", "name": "Custom Mattress", "category": "MATTRESS",
        "base_price_cents": 80000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "QUEEN", "surcharge_cents": 0}],
        "is_special_order": True, "lead_days": 14}, SM))
    customer = create_customer()
    route = create_route(capacity_units=5)  # 2026-03-01, plenty of capacity
    order_b = create_draft_order(customer["id"])
    add_line(order_b["id"], special["id"], fabric_code="STANDARD", size_code="QUEEN")
    pay_in_full(order_b["id"])
    confirm(order_b["id"])
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 600, "window_end_minute": 660,
        "expected_route_version": fresh["version"]}, DD)
    validate_error(res, "ERR_LEAD_TIME_NOT_MET")


# ─── Difficulty: THRESHOLD adjacent vs overlapping windows ────────────────
def test_threshold_adjacent_window_admitted(api):
    """PRD 3.8: "The requested window, including the white-glove buffer where it applies,
    must not overlap any existing `BOOKED` or `DISPATCHED` stop on the same route; an
    overlap is rejected with `ERR_STOP_OVERLAP`."

    A THRESHOLD stop 600-660 admits an adjacent 660-720 (touching boundary, no overlap).

    Design: Difficulty/resource_temporal_overlap/threshold_adjacent_windows_no_buffer_no_overlap_then_overlap
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=10)
    order_a = _confirmed_order(api, customer["id"], product["id"])
    book_stop(route["id"], order_a["id"], route["version"],
              window_start_minute=600, window_end_minute=660)
    order_b = _confirmed_order(api, customer["id"], product["id"])
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 660, "window_end_minute": 720,
        "expected_route_version": fresh["version"]}, DD)
    stop_b = validate_success(res, 201)
    assert stop_b["status"] == "BOOKED", "adjacent THRESHOLD window does not overlap"


def test_threshold_overlapping_window_rejected(api):
    """PRD 3.8: "The requested window ... must not overlap any existing BOOKED or
    DISPATCHED stop on the same route; an overlap is rejected with ERR_STOP_OVERLAP."

    Existing 600-660 rejects a 650-710 window that overlaps it.

    Design: Difficulty/resource_temporal_overlap/threshold_adjacent_windows_no_buffer_no_overlap_then_overlap
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=10)
    order_a = _confirmed_order(api, customer["id"], product["id"])
    book_stop(route["id"], order_a["id"], route["version"],
              window_start_minute=600, window_end_minute=660)
    order_b = _confirmed_order(api, customer["id"], product["id"])
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 650, "window_end_minute": 710,
        "expected_route_version": fresh["version"]}, DD)
    validate_error(res, "ERR_STOP_OVERLAP")


# ─── Difficulty: WHITE_GLOVE buffer extends occupancy ─────────────────────
def test_white_glove_buffer_extends_occupancy_overlap(api):
    """PRD 3.8: "a `WHITE_GLOVE` stop additionally requires a service buffer to fit after
    the window before the next stop ..."
    PRD 3.8: "The requested window, including the white-glove buffer where it applies,
    must not overlap any existing BOOKED or DISPATCHED stop on the same route; an overlap
    is rejected with ERR_STOP_OVERLAP."

    A WHITE_GLOVE stop 600-660 occupies past 660 via its buffer, so a 680-740 stop
    overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/white_glove_buffer_extends_occupancy_into_following_window
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=10)
    order_a = _confirmed_order(api, customer["id"], product["id"], tier="WHITE_GLOVE")
    book_stop(route["id"], order_a["id"], route["version"],
              window_start_minute=600, window_end_minute=660)
    order_b = _confirmed_order(api, customer["id"], product["id"], tier="THRESHOLD")
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 680, "window_end_minute": 740,
        "expected_route_version": fresh["version"]}, DD)
    validate_error(res, "ERR_STOP_OVERLAP")


def test_white_glove_stop_copies_service_tier(api):
    """PRD 3.8: "At booking the stop copies its `service_tier` from the order's
    `delivery_tier` ..."

    Second test for this instance: a WHITE_GLOVE order's stop carries WHITE_GLOVE tier,
    the buffer geometry that drives the overlap above.

    Design: Difficulty/resource_temporal_overlap/white_glove_buffer_extends_occupancy_into_following_window
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=10)
    order_a = _confirmed_order(api, customer["id"], product["id"], tier="WHITE_GLOVE")
    stop = book_stop(route["id"], order_a["id"], route["version"],
                     window_start_minute=600, window_end_minute=660)
    assert stop["service_tier"] == "WHITE_GLOVE"


# ─── Difficulty: compensating invariant — committed_units conserved ───────
def test_book_then_cancel_conserves_committed_units(api):
    """PRD 2.7: "Booking a stop adds to this tally and cancelling or completing a stop
    subtracts from it ..."
    PRD 3.9: "A dispatcher may instead cancel a still-booked stop, moving it `BOOKED →
    CANCELLED`; cancellation decrements the route's `committed_units` by the stop's
    `unit_load` ..."

    Booking adds unit_load 1 (committed 1), cancelling subtracts it back to 0.

    Design: Difficulty/compensating_invariant/stop_book_then_cancel_conserves_route_committed_units
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    order = _confirmed_order(api, customer["id"], product["id"])
    stop = book_stop(route["id"], order["id"], route["version"])
    after_book = get_success_data(api.get_delivery_route(route["id"], DD))
    assert after_book["committed_units"] == 1
    get_success_data(api.cancel_delivery_stop(stop["id"], DD))
    after_cancel = get_success_data(api.get_delivery_route(route["id"], DD))
    assert after_cancel["committed_units"] == 0, "cancel restores committed_units to 0"


def test_book_increments_then_cancel_reverts_to_confirmed(api):
    """PRD 3.9: "when this was the order's only active stop — bubbles the order's
    `fulfillment_status` back from `SCHEDULED` to `CONFIRMED` ..."

    Second test for this conserved-quantity instance: the order also reverts to CONFIRMED
    when its only stop is cancelled, confirming the ledger and the order both unwind.

    Design: Difficulty/compensating_invariant/stop_book_then_cancel_conserves_route_committed_units
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    order = _confirmed_order(api, customer["id"], product["id"])
    stop = book_stop(route["id"], order["id"], route["version"])
    scheduled = get_success_data(api.get_order(order["id"], SA))
    assert scheduled["fulfillment_status"] == "SCHEDULED"
    get_success_data(api.cancel_delivery_stop(stop["id"], DD))
    reverted = get_success_data(api.get_order(order["id"], SA))
    assert reverted["fulfillment_status"] == "CONFIRMED"


# ─── Corner: window out of shift ──────────────────────────────────────────
def test_window_out_of_shift_rejected(api):
    """PRD 3.8: "a window that falls outside the shift, or whose white-glove buffer would
    run past the shift end, is rejected with `ERR_WINDOW_OUT_OF_SHIFT`."

    Shift 480-1080; a 1040-1100 window runs past shift end 1080.

    Design: Corner/validations/stop_window_out_of_shift_returns_window_out_of_shift
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    order = _confirmed_order(api, customer["id"], product["id"])
    fresh = get_success_data(api.get_delivery_route(route["id"], DD))
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order["id"],
        "window_start_minute": 1040, "window_end_minute": 1100,
        "expected_route_version": fresh["version"]}, DD)
    validate_error(res, "ERR_WINDOW_OUT_OF_SHIFT")


# ─── Corner: route complete with unresolved stops ─────────────────────────
def test_route_complete_with_booked_stop_rejected(api):
    """PRD 3.8: "completion is allowed only when every stop on the route is already in
    `COMPLETED` or `CANCELLED` status, and an attempt to complete a route with stops still
    `BOOKED` or `DISPATCHED` is rejected with `ERR_STOPS_UNRESOLVED`."

    Design: Corner/errors/route_complete_with_unresolved_stops_returns_stops_unresolved
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    order = _confirmed_order(api, customer["id"], product["id"])
    book_stop(route["id"], order["id"], route["version"])  # remains BOOKED
    get_success_data(api.lock_delivery_route(route["id"], DD))
    res = api.complete_delivery_route(route["id"], DD)
    validate_error(res, "ERR_STOPS_UNRESOLVED")


# ─── Corner: cancel order with active stop ────────────────────────────────
def test_cancel_order_with_active_stop_rejected(api):
    """PRD 3.11: "A SalesAssociate may cancel an order while its `fulfillment_status` is
    `DRAFT` or `CONFIRMED`, provided the order has no `DeliveryStop` in `BOOKED` or
    `DISPATCHED` status; an active stop blocks the cancellation with `ERR_STOP_ACTIVE`
    ..."

    Design: Corner/errors/cancel_order_with_active_stop_returns_stop_active
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    order = _confirmed_order(api, customer["id"], product["id"])
    book_stop(route["id"], order["id"], route["version"])  # BOOKED stop
    res = api.cancel_order(order["id"], SA)
    validate_error(res, "ERR_STOP_ACTIVE")


# ─── Corner: OCC stale route version on stop booking ──────────────────────
def test_stop_booking_stale_route_version_rejected(api):
    """PRD 2.10: "Booking a delivery stop requires the request to include
    `expected_route_version` carrying the client's last-observed `version` of the target
    `DeliveryRoute`; if that value does not equal the route's current `version` ... the
    booking is rejected with `ERR_STALE_VERSION` (HTTP 412) ..."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_on_stop_booking_returns_412
    """
    product = create_sofa_product()
    customer = create_customer()
    route = create_route(capacity_units=5)
    stale_v = route["version"]
    order_a = _confirmed_order(api, customer["id"], product["id"])
    order_b = _confirmed_order(api, customer["id"], product["id"])
    book_stop(route["id"], order_a["id"], stale_v)  # first booking bumps route.version
    res = api.create_delivery_stop({
        "route_id": route["id"], "order_id": order_b["id"],
        "window_start_minute": 700, "window_end_minute": 760,
        "expected_route_version": stale_v}, DD)  # reuses pre-first version
    validate_error(res, "ERR_STALE_VERSION")
