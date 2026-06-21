"""Booking reservation lifecycle: the RESERVED branch (arrive vs no-show), fee accounting
(net-zero refund, late-cancel forfeit, immediate balance), and the temporal-overlap
constraints on spots and staff shifts.

Queue A: non_linear_state_machine/booking_branching_reserved_to_noshow_vs_arrived,
         compensating_invariant/reservation_fee_balance_net_zero_on_full_refund_cancel,
         resource_temporal_overlap/spot_capacity_overlap_with_buffer,
         resource_temporal_overlap/staff_shift_overlap_no_buffer_adjacency_allowed.
Queue B: late_cancel_forfeits_fee, immediate_consistency..., filtered_list_bookings_by_event.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_reserved_booking, make_operable_truck, set_clock,
    create_commissary, create_truck, issue_permit, add_shift,
    create_spot, create_event, reserve_booking, read_truck_version,
    api_client, TEST_USERS, make_operator_truck_headers, create_booking_payload,
    create_staff_shift_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── non_linear_state_machine / booking branch RESERVED -> NO_SHOW ──────────

def test_booking_no_show_on_clock_sweep_forfeits_fee(api):
    """PRD §3.4: "If the clock advances to or past a `RESERVED` booking's `window_end` while it
    is still `RESERVED`, the sweep transitions it `RESERVED → NO_SHOW`. The fee is forfeited:
    `fee_refunded_cents` stays 0, and the booking continues to count toward the truck's
    `reservation_fee_balance_cents`."

    Advancing the clock to window_end on a still-RESERVED booking yields NO_SHOW with
    fee_refunded_cents 0.

    Design: Difficulty/non_linear_state_machine/booking_branching_reserved_to_noshow_vs_arrived
    """
    ctx = setup_reserved_booking(
        "2026-06-06", clock_iso="2026-06-06T18:00:00.000Z",
        reservation_fee_cents=2500,
        window_start="2026-06-06T19:00:00.000Z", window_end="2026-06-06T21:00:00.000Z")
    set_clock("2026-06-06T21:00:00.000Z")
    after = validate_success(api.get_booking(ctx["booking"]["id"], DISPATCHER), 200)
    assert after["status"] == "NO_SHOW"
    assert after["fee_refunded_cents"] == 0


def test_booking_branch_arrive_keeps_fee_distinct_from_noshow(api):
    """PRD §3.4: "The truck arrives at its spot, the transition `RESERVED → ARRIVED`."
    PRD §2.8: "A `NO_SHOW` booking deliberately keeps its fee in the balance: the fee is
    forfeited, not refunded."

    From the same RESERVED start, taking the manual ARRIVE fork (rather than the clock-driven
    NO_SHOW fork) reaches ARRIVED with fee_refunded_cents still 0 — the fork that keeps the fee
    live in the truck's balance.

    Design: Difficulty/non_linear_state_machine/booking_branching_reserved_to_noshow_vs_arrived
    """
    ctx = setup_reserved_booking(
        "2026-06-27", clock_iso="2026-06-27T19:30:00.000Z",
        reservation_fee_cents=2500,
        window_start="2026-06-27T19:00:00.000Z", window_end="2026-06-27T21:00:00.000Z")
    h = make_operator_truck_headers(ctx["truck"]["id"])
    arrived = validate_success(api.arrive_booking(ctx["booking"]["id"], h), 200)
    assert arrived["status"] == "ARRIVED"
    assert arrived["fee_refunded_cents"] == 0
    truck = validate_success(api.get_truck(ctx["truck"]["id"], DISPATCHER), 200)
    assert truck["reservation_fee_balance_cents"] == 2500


# ─── compensating_invariant / fee balance net-zero on full refund ───────────

def test_reservation_fee_balance_net_zero_on_full_refund_cancel(api):
    """PRD §3.4: "it is a clean cancel and the full fee is refunded — `fee_refunded_cents` is set
    equal to `reservation_fee_cents`."
    PRD §3.4: "Across a reserve-then-fully-refunded-cancel pair, a truck's
    `reservation_fee_balance_cents` returns to exactly its pre-reservation value."

    Booking a 2500-fee spot debits the balance to 2500; an early (pre-cutoff) cancel refunds in
    full and returns the balance to 0.

    Design: Difficulty/compensating_invariant/reservation_fee_balance_net_zero_on_full_refund_cancel
    """
    set_clock("2026-06-17T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-06-17T18:00:00.000Z", "2026-06-17T23:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-06-17T19:00:00.000Z", "2026-06-17T22:00:00.000Z")
    after_book = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert after_book["reservation_fee_balance_cents"] == 2500
    h = make_operator_truck_headers(truck["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], h), 200)
    assert cancelled["fee_refunded_cents"] == 2500
    after_cancel = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert after_cancel["reservation_fee_balance_cents"] == 0


def test_full_refund_cancel_sets_fee_refunded_to_full_fee(api):
    """PRD §3.4: "it is a clean cancel and the full fee is refunded — `fee_refunded_cents` is set
    equal to `reservation_fee_cents`."

    The cancelled booking's fee_refunded_cents equals the snapshotted 2500 fee, the credit term
    that makes the truck balance net to zero.

    Design: Difficulty/compensating_invariant/reservation_fee_balance_net_zero_on_full_refund_cancel
    """
    set_clock("2026-06-28T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-06-28T18:00:00.000Z", "2026-06-28T23:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-06-28T19:00:00.000Z", "2026-06-28T22:00:00.000Z")
    h = make_operator_truck_headers(truck["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], h), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_refunded_cents"] == 2500


# ─── resource_temporal_overlap / spot capacity with buffer ──────────────────

def test_spot_capacity_exceeded_within_buffer(api):
    """PRD §3.4: "A new RESERVED booking's window, padded by the spot's buffer_minutes on both
    ends, must not push the number of concurrently-overlapping non-terminal bookings on that
    spot above the spot's concurrent_capacity; if it would, the reservation is rejected with
    ERR_SPOT_CAPACITY_EXCEEDED."

    Capacity 1 with a 30-minute buffer: truck B's 19:20-20:00 window starts only 20 min after
    truck A's 18:00-19:00 window ends — inside the buffer pad — so it overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/spot_capacity_overlap_with_buffer
    """
    set_clock("2026-06-15T10:00:00.000Z")
    commissary = create_commissary()
    truck_a = create_truck(commissary["id"])
    issue_permit(truck_a["id"])
    truck_b = create_truck(commissary["id"])
    issue_permit(truck_b["id"])
    spot = create_spot(concurrent_capacity=1, reservation_fee_cents=500, buffer_minutes=30)
    event = create_event("2026-06-15T17:00:00.000Z", "2026-06-15T23:00:00.000Z")
    reserve_booking(truck_a["id"], spot["id"], event["id"],
                    "2026-06-15T18:00:00.000Z", "2026-06-15T19:00:00.000Z")
    version_b = read_truck_version(truck_b["id"])
    h_b = make_operator_truck_headers(truck_b["id"])
    res = api.create_booking(
        create_booking_payload(truck_b["id"], spot["id"], event["id"],
                               "2026-06-15T19:20:00.000Z", "2026-06-15T20:00:00.000Z", version_b), h_b)
    validate_error(res, "ERR_SPOT_CAPACITY_EXCEEDED")


def test_spot_capacity_allows_nonoverlapping_booking(api):
    """PRD §3.4: "Overlap is computed on half-open intervals, so two windows that merely touch
    at a shared endpoint with zero buffer do not count as overlapping."

    Capacity 1 with zero buffer: truck B's window starting exactly at truck A's window_end does
    not overlap, so the second reservation succeeds.

    Design: Difficulty/resource_temporal_overlap/spot_capacity_overlap_with_buffer
    """
    set_clock("2026-06-29T10:00:00.000Z")
    commissary = create_commissary()
    truck_a = create_truck(commissary["id"])
    issue_permit(truck_a["id"])
    truck_b = create_truck(commissary["id"])
    issue_permit(truck_b["id"])
    spot = create_spot(concurrent_capacity=1, reservation_fee_cents=500, buffer_minutes=0)
    event = create_event("2026-06-29T17:00:00.000Z", "2026-06-29T23:00:00.000Z")
    reserve_booking(truck_a["id"], spot["id"], event["id"],
                    "2026-06-29T18:00:00.000Z", "2026-06-29T19:00:00.000Z")
    version_b = read_truck_version(truck_b["id"])
    h_b = make_operator_truck_headers(truck_b["id"])
    res = api.create_booking(
        create_booking_payload(truck_b["id"], spot["id"], event["id"],
                               "2026-06-29T19:00:00.000Z", "2026-06-29T20:00:00.000Z", version_b), h_b)
    booking = validate_success(res, 201)
    assert booking["status"] == "RESERVED"


# ─── resource_temporal_overlap / staff shift overlap (no buffer) ────────────

def test_staff_shift_overlap_rejected(api):
    """PRD §3.8: "A new shift for a given worker on a given truck must not overlap any existing
    SCHEDULED shift for that same (truck_id, staff_name) pair; overlap uses the half-open
    interval [shift_start, shift_end) ... A violating shift is rejected with ERR_SHIFT_OVERLAP."

    A second shift for worker 'Sam' starting 17:59 overlaps the existing 16:00-18:00 shift by
    one minute and is rejected.

    Design: Difficulty/resource_temporal_overlap/staff_shift_overlap_no_buffer_adjacency_allowed
    """
    set_clock("2026-06-16T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    add_shift(truck["id"], "COOK", "2026-06-16T16:00:00.000Z", "2026-06-16T18:00:00.000Z", staff_name="Sam")
    h = make_operator_truck_headers(truck["id"])
    res = api.create_staff_shift(
        create_staff_shift_payload(truck["id"], "COOK", "2026-06-16T17:59:00.000Z",
                                   "2026-06-16T19:00:00.000Z", staff_name="Sam"), h)
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_staff_shift_adjacency_allowed(api):
    """PRD §3.8: "overlap uses the half-open interval [shift_start, shift_end), so two shifts
    that are merely adjacent at a shared endpoint are allowed, and there is no buffer."

    A second shift for worker 'Sam' starting exactly at 18:00 (the first shift's end) is
    adjacent, not overlapping, and is accepted.

    Design: Difficulty/resource_temporal_overlap/staff_shift_overlap_no_buffer_adjacency_allowed
    """
    set_clock("2026-06-30T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    add_shift(truck["id"], "COOK", "2026-06-30T16:00:00.000Z", "2026-06-30T18:00:00.000Z", staff_name="Sam")
    h = make_operator_truck_headers(truck["id"])
    res = api.create_staff_shift(
        create_staff_shift_payload(truck["id"], "COOK", "2026-06-30T18:00:00.000Z",
                                   "2026-06-30T20:00:00.000Z", staff_name="Sam"), h)
    shift = validate_success(res, 201)
    assert shift["status"] == "SCHEDULED"


# ─── Corner: late cancel forfeits, immediate consistency, filtered list ─────

def test_late_cancel_forfeits_fee(api):
    """PRD §3.4: "it is a late cancel and nothing is refunded — `fee_refunded_cents` stays 0."

    Cancelling 30 minutes before window_start (inside the 120-minute cutoff) refunds 0, so the
    cancelled booking's fee_refunded_cents stays at 0.

    Design: Corner/cross_cutting_complexity_layers/late_cancel_forfeits_fee
    """
    set_clock("2026-07-16T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-07-16T17:00:00.000Z", "2026-07-16T23:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-07-16T19:00:00.000Z", "2026-07-16T22:00:00.000Z")
    set_clock("2026-07-16T18:30:00.000Z")
    h = make_operator_truck_headers(truck["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], h), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_refunded_cents"] == 0


def test_immediate_consistency_balance_after_booking(api):
    """PRD §3.4: "On reservation the booking enters RESERVED, its reservation_fee_cents is
    snapshotted from the spot's current reservation_fee_cents ... and the snapshotted fee is
    added to the owning truck's reservation_fee_balance_cents."

    A GET on the truck immediately after a booking create reflects the debited
    reservation_fee_balance_cents (2500) with no lag.

    Design: Corner/consistency_model/immediate_consistency_booking_balance_in_same_response_chain
    """
    set_clock("2026-07-18T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=2500)
    event = create_event("2026-07-18T17:00:00.000Z", "2026-07-18T22:00:00.000Z")
    reserve_booking(truck["id"], spot["id"], event["id"],
                    "2026-07-18T18:00:00.000Z", "2026-07-18T19:00:00.000Z")
    truck_after = validate_success(api.get_truck(truck["id"], DISPATCHER), 200)
    assert truck_after["reservation_fee_balance_cents"] == 2500


def test_filtered_list_bookings_by_event(api):
    """PRD §3.4: "Bookings may be listed with optional `truck_id`, `spot_id`, and `event_id`
    filters."

    GET /bookings?event_id=<id> returns exactly the one booking placed on that event.

    Design: Corner/endpoints/filtered_list_bookings_by_event
    """
    set_clock("2026-07-12T10:00:00.000Z")
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    issue_permit(truck["id"])
    spot = create_spot(concurrent_capacity=2, reservation_fee_cents=500)
    event = create_event("2026-07-12T17:00:00.000Z", "2026-07-12T22:00:00.000Z")
    booking = reserve_booking(truck["id"], spot["id"], event["id"],
                              "2026-07-12T18:00:00.000Z", "2026-07-12T19:00:00.000Z")
    data, meta = validate_paginated(api.list_bookings(DISPATCHER, params={"event_id": event["id"]}))
    assert [b["id"] for b in data] == [booking["id"]]
