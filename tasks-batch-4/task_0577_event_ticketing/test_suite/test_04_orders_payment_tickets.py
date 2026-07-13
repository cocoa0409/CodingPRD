"""Order creation & fee math, payment cascades, auth-over-state priority, ticket
parallel dimensions, and fulfillment/scan gating."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_buyer_headers,
    register_buyer, setup_onsale_event, setup_admitted_buyer_on_onsale_event,
    setup_paid_order, admit_buyer, hold_seats, create_order, pay_order, event_version,
    set_clock,
)

BOX = TEST_USERS["box_office_headers"]
GATE = TEST_USERS["gate_scanner_headers"]


def _pending_order(api, num_seats):
    """A PENDING order over `num_seats` seats (base 9990, dynamic off, MOBILE)."""
    env = setup_admitted_buyer_on_onsale_event(
        num_seats=num_seats, base_face_value_cents=9990, dynamic_pricing_enabled=False,
    )
    ev_id = env["event"]["id"]
    seat_ids = [s["id"] for s in env["seats"]]
    hold = hold_seats(ev_id, seat_ids, env["buyer"]["id"])
    return create_order(hold["id"], env["buyer"]["id"], "MOBILE")


# ─── Difficulty: per-seat-then-sum service fee ────────────────────────────
def test_service_fee_rounds_per_seat_then_sums_two_seats(api):
    """PRD §3.4: "for each seat in the hold, take that seat's locked face value, multiply by
    the price level's `service_fee_pct`, round half up to whole cents, add the price level's
    `service_fee_flat_cents`, and only then sum these per-seat amounts across all seats."

    Design: Difficulty/combinatorial_formula/order_service_fee_round_per_seat_then_sum
    """
    order = _pending_order(api, num_seats=2)
    # Per seat: round_half_up(9990 * 0.15 = 1498.5) = 1499, + 500 flat = 1999; x2 = 3998.
    assert order["face_total_cents"] == 19980
    assert order["service_fee_cents"] == 3998
    assert order["order_total_cents"] == 23978


def test_service_fee_single_seat_rounds_half_up(api):
    """PRD §3.4: "for each seat in the hold, take that seat's locked face value, multiply by
    the price level's `service_fee_pct`, round half up to whole cents, add the price level's
    `service_fee_flat_cents`, and only then sum these per-seat amounts across all seats."
    PRD §3.4: "The order's `order_total_cents` is `face_total_cents` plus `service_fee_cents`."

    Design: Difficulty/combinatorial_formula/order_service_fee_round_per_seat_then_sum
    """
    order = _pending_order(api, num_seats=1)
    # round_half_up(9990 * 0.15 = 1498.5) = 1499, + 500 flat = 1999.
    assert order["face_total_cents"] == 9990
    assert order["service_fee_cents"] == 1999
    assert order["order_total_cents"] == 11989


# ─── Difficulty: pay cascade (order -> hold -> seat) ──────────────────────
def test_pay_converts_hold_and_sells_seat(api):
    """PRD §3.4: "the backing hold moves from `ACTIVE` to `CONVERTED` and each of its `HELD`
    seats becomes `SOLD`".

    Design: Difficulty/transitive_cascade/pay_cascades_hold_converted_seat_sold
    """
    p = setup_paid_order(num_seats=1)
    hold = validate_success(api.get_hold(p["hold"]["id"], BOX), 200)
    assert hold["status"] == "CONVERTED"
    seat = validate_success(api.get_seat(p["seats"][0]["id"], BOX), 200)
    assert seat["status"] == "SOLD"


def test_pay_updates_event_inventory_counts(api):
    """PRD §2.8: inventory counters are "recomputed after any seat status change (hold
    creation, release, expiry, payment, refund, or voiding)"; payment turns HELD seats SOLD.

    Design: Difficulty/transitive_cascade/pay_cascades_hold_converted_seat_sold
    """
    p = setup_paid_order(num_seats=1)
    event = validate_success(api.get_event(p["event"]["id"], BOX), 200)
    assert event["seats_sold"] == 1
    assert event["seats_held"] == 0


# ─── Difficulty: authorization outranks state ─────────────────────────────
def test_pay_by_non_owner_returns_unauthorized_over_state(api):
    """PRD §2.9: the validation order runs "(2) authorization of the acting role and, for
    buyers, ownership of the target resource, failing with `ERR_UNAUTHORIZED`" before the
    state-legality check. PRD §2.1: an order's `buyer_id` "must equal the acting buyer's
    `X-User-ID` for that buyer to mutate the resource."

    Design: Difficulty/priority_pair_validation_conflict/pay_unauthorized_beats_already_paid_state
    """
    p = setup_paid_order(num_seats=1)  # B1's order is already PAID
    intruder = register_buyer()
    res = api.pay_order(p["order"]["id"], make_buyer_headers(intruder["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_rejected_non_owner_pay_leaves_order_unchanged(api):
    """PRD §2.1: an order's `buyer_id` "must equal the acting buyer's `X-User-ID` for that
    buyer to mutate the resource." PRD §3.4: on payment "the order's `paid_amount_cents` is
    set to its `order_total_cents`" — an unauthorized attempt changes nothing.

    Design: Difficulty/priority_pair_validation_conflict/pay_unauthorized_beats_already_paid_state
    """
    p = setup_paid_order(num_seats=1)
    intruder = register_buyer()
    api.pay_order(p["order"]["id"], make_buyer_headers(intruder["id"]))
    order = validate_success(api.get_order(p["order"]["id"], make_buyer_headers(p["buyer"]["id"])), 200)
    assert order["status"] == "PAID"
    assert order["paid_amount_cents"] == order["order_total_cents"]


# ─── Difficulty: ticket parallel dimensions ───────────────────────────────
def test_deliver_advances_only_delivery_dimension(api):
    """PRD §3.5: "Delivering a ticket moves its `delivery_status` from `PENDING` to
    `DELIVERED` and leaves the validity and scan dimensions untouched; it is legal only when
    the ticket is `VALID` and its `delivery_status` is still `PENDING`."

    Design: Difficulty/non_linear_state_machine/ticket_parallel_dimensions_independent
    """
    p = setup_paid_order(num_seats=1, delivery_method="PRINT")
    ticket_id = p["tickets"][0]["id"]
    delivered = validate_success(api.deliver_ticket(ticket_id, BOX), 200)
    assert delivered["status"] == "VALID"
    assert delivered["delivery_status"] == "DELIVERED"
    assert delivered["scan_status"] == "UNSCANNED"


def test_scan_advances_only_scan_dimension(api):
    """PRD §3.5: "Scanning moves the ticket's `scan_status` from `UNSCANNED` to `SCANNED` and
    touches neither validity nor delivery." PRD §3.5: "A scan is admitted only when the ticket
    is `VALID`, its `delivery_status` is `DELIVERED`, its `scan_status` is still `UNSCANNED`,
    and the event is `ONSALE`".

    Design: Difficulty/non_linear_state_machine/ticket_parallel_dimensions_independent
    """
    p = setup_paid_order(num_seats=1, delivery_method="PRINT")
    ticket_id = p["tickets"][0]["id"]
    validate_success(api.deliver_ticket(ticket_id, BOX), 200)
    scanned = validate_success(api.scan_ticket(ticket_id, GATE), 200)
    assert scanned["status"] == "VALID"
    assert scanned["delivery_status"] == "DELIVERED"
    assert scanned["scan_status"] == "SCANNED"


# ─── Corner: payment temporal gate + consistency + listing ────────────────
def test_pay_expired_hold_returns_hold_expired(api):
    """PRD §3.4: "Payment is legal only while the hold is still `ACTIVE` and not expired (the
    clock is strictly before the hold's `expires_at`, else `ERR_HOLD_EXPIRED`) and while the
    event is `ONSALE` or `PRESALE`."

    Design: Corner/validations/pay_expired_hold_returns_hold_expired
    """
    set_clock("2026-06-01T10:00:00Z")
    buyer = register_buyer()
    env = setup_onsale_event(num_seats=1, hold_ttl_minutes=15)
    ev_id = env["event"]["id"]
    admit_buyer(ev_id, buyer["id"])
    hold = hold_seats(ev_id, [env["seats"][0]["id"]], buyer["id"])  # expires 10:15
    order = create_order(hold["id"], buyer["id"], "MOBILE")

    set_clock("2026-06-01T10:20:00Z")  # past expires_at
    res = api.pay_order(order["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_HOLD_EXPIRED.value, expected_status=409)


def test_pay_response_reflects_sold_seats_immediately(api):
    """PRD §3.4: "the backing hold moves from `ACTIVE` to `CONVERTED` and each of its `HELD`
    seats becomes `SOLD`". PRD §2.8: the counters are "recomputed after any seat status
    change (hold creation, release, expiry, payment, refund, or voiding)."

    Design: Corner/consistency_model/pay_response_reflects_sold_seats_immediately
    """
    p = setup_paid_order(num_seats=1)
    event = validate_success(api.get_event(p["event"]["id"], BOX), 200)
    assert event["seats_sold"] == 1
    assert event["seats_held"] == 0
    assert event["seats_available"] == 0


def test_orders_filtered_list_by_buyer_reverse_reach(api):
    """PRD §4: `GET /orders` — "List orders filtered by event, buyer, or hold". PRD §2.3:
    list responses carry `total_count`, "the number of matching items before pagination".

    Design: Corner/endpoints/orders_filtered_list_by_buyer_reverse_reach
    """
    p = setup_paid_order(num_seats=1)
    buyer_id = p["buyer"]["id"]
    data, meta = validate_paginated(
        api.list_orders(make_buyer_headers(buyer_id), params={"buyer_id": buyer_id})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == p["order"]["id"]


# ─── Corner: fulfillment/scan gating ──────────────────────────────────────
def test_scan_undelivered_ticket_returns_not_delivered(api):
    """PRD §3.5: "A scan of an undelivered ticket is rejected with `ERR_TICKET_NOT_DELIVERED`,
    and a scan of one already scanned with `ERR_TICKET_ALREADY_SCANNED`."

    Design: Corner/validations/scan_undelivered_ticket_returns_not_delivered
    """
    p = setup_paid_order(num_seats=1, delivery_method="PRINT")  # ticket delivery still PENDING
    res = api.scan_ticket(p["tickets"][0]["id"], GATE)
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_DELIVERED.value, expected_status=409)


def test_deliver_already_delivered_returns_invalid_state(api):
    """PRD §3.5: delivering "is legal only when the ticket is `VALID` and its
    `delivery_status` is still `PENDING`. Mobile tickets arrive `DELIVERED` at issuance and
    need no such step." PRD §2.9: "(5) that the target resource is in a state from which the
    requested transition is legal, failing with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/deliver_already_delivered_returns_invalid_state
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")  # auto-DELIVERED at pay
    res = api.deliver_ticket(p["tickets"][0]["id"], BOX)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
