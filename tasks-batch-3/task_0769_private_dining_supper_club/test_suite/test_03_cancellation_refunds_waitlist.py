"""Cancellation cascades, tiered refunds, waitlist promotion/expiry, revenue recognition, and
the parallel booking status dimensions.

Each test translates exactly one design-index instance; docstrings end with the Design tag.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    provision_open_event, provision_confirmed_booking,
    create_guest, book_seats, pay_deposit, join_waitlist,
    get_event, get_booking, get_waitlist_entry, get_seat_by_id, get_booking_payments,
    set_clock, make_guest_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: transitive_cascade / event cancel -> booking -> seat ──

def test_event_cancel_cancels_booking_and_full_refund(api):
    """PRD §3.9: "the guest receives a full refund, so refund_cents is set equal to
    deposit_paid_cents (an event-driven cancellation always refunds 100% of what was paid,
    regardless of how many days remain before the event), a Payment entry with kind of REFUND and
    direction of REFUND is appended for that amount, and payment_status becomes REFUNDED".

    Design: Difficulty/transitive_cascade/event_cancel_booking_refund_seat_chain
    """
    ctx, _guest, booking = provision_confirmed_booking(
        seat_count=1, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    assert booking["deposit_paid_cents"] == 2500
    cancelled = validate_success(
        api.cancel_event(ctx["event"]["id"], {"reason": "chef ill"}, ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    after = get_booking(booking["id"])
    assert after["booking_status"] == "CANCELLED"
    assert after["payment_status"] == "REFUNDED"
    assert after["refund_cents"] == 2500, after["refund_cents"]


def test_event_cancel_frees_seat_and_appends_refund_payment(api):
    """PRD §3.9: "each seat held by a cancelled booking transitions from BOOKED or HELD back to
    AVAILABLE and has its current_booking_id cleared. After the booking cascade completes, any seat
    that is still AVAILABLE (or was HELD by nothing) is taken out of service by transitioning it to
    BLOCKED." The freed seat's final observable status is therefore BLOCKED with a cleared
    current_booking_id.

    Design: Difficulty/transitive_cascade/event_cancel_booking_refund_seat_chain
    """
    ctx, _guest, booking = provision_confirmed_booking(
        seat_count=1, seat_price_cents=10000, deposit_pct=0.25, table_mode="PRIVATE")
    seat_id = ctx["seats"][0]["id"]
    validate_success(api.cancel_event(ctx["event"]["id"], {"reason": "x"}, ADMIN), 200)
    seat = get_seat_by_id(ctx["event"]["id"], seat_id)
    assert seat["status"] == "BLOCKED", seat["status"]
    assert seat["current_booking_id"] is None, seat["current_booking_id"]
    payments = get_booking_payments(booking["id"])
    refunds = [p for p in payments if p["kind"] == "REFUND" and p["amount_cents"] == 2500]
    assert len(refunds) == 1, payments


# ─── Difficulty: transitive_cascade / booking cancel -> seat -> waitlist ─

def test_booking_cancel_promotes_front_waitlist_entry(api):
    """PRD §3.6: "That entry is promoted WAITING → PROMOTED, and the system auto-creates a Booking
    for its guest in PENDING_DEPOSIT / UNPAID, holding the freed seat(s); the promoted entry's
    booking_id is set to that new booking's id."

    Design: Difficulty/transitive_cascade/booking_cancel_frees_seat_promotes_waitlist_chain
    """
    ctx, g1, b1 = provision_confirmed_booking(seat_count=1)  # event now full (1 seat sold)
    g2 = create_guest(email="g2@x.com")
    w2 = join_waitlist(ctx["event"]["id"], g2["id"], party_size=1)
    validate_success(api.cancel_booking(b1["id"], {"reason": "can't make it"},
                                        make_guest_headers(g1["id"])), 200)
    entry = get_waitlist_entry(w2["id"])
    assert entry["status"] == "PROMOTED", entry["status"]
    assert entry["booking_id"] is not None


def test_booking_cancel_autocreates_pending_booking_for_promoted_guest(api):
    """PRD §3.6: "the system auto-creates a Booking for its guest in PENDING_DEPOSIT / UNPAID,
    holding the freed seat(s)".

    Design: Difficulty/transitive_cascade/booking_cancel_frees_seat_promotes_waitlist_chain
    """
    ctx, g1, b1 = provision_confirmed_booking(seat_count=1)
    g2 = create_guest(email="g2@x.com")
    join_waitlist(ctx["event"]["id"], g2["id"], party_size=1)
    validate_success(api.cancel_booking(b1["id"], {"reason": "x"},
                                        make_guest_headers(g1["id"])), 200)
    data, meta = validate_paginated(api.list_bookings(ADMIN, params={"guest_id": g2["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert data[0]["booking_status"] == "PENDING_DEPOSIT", data[0]["booking_status"]


# ─── Difficulty: boundary_precision_check / refund 14-day boundary ─────

def test_refund_exactly_14_days_full_refund(api):
    """PRD §3.6: "If that day count is at least 14, the refund rate is the full 1.00".

    Design: Difficulty/boundary_precision_check/refund_tier_14_day_boundary
    """
    # event_start 2026-03-15T00:00; clock at default 2026-03-01 -> exactly 14 days out.
    _ctx, guest, booking = provision_confirmed_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25,
        event_overrides={"event_start": "2026-03-15T00:00:00Z",
                         "event_end": "2026-03-15T04:00:00Z"})
    assert booking["deposit_paid_cents"] == 5000
    cancelled = validate_success(
        api.cancel_booking(booking["id"], {"reason": "conflict"},
                           make_guest_headers(guest["id"])), 200)
    assert cancelled["refund_cents"] == 5000, cancelled["refund_cents"]
    assert cancelled["payment_status"] == "REFUNDED"


def test_refund_13_days_below_boundary_half_refund(api):
    """PRD §3.6: "if it is at least 7 but fewer than 14, the rate is 0.50".

    Design: Difficulty/boundary_precision_check/refund_tier_14_day_boundary
    """
    _ctx, guest, booking = provision_confirmed_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25,
        event_overrides={"event_start": "2026-03-15T00:00:00Z",
                         "event_end": "2026-03-15T04:00:00Z"})
    set_clock("2026-03-02T00:00:00Z")  # 13 days before event_start -> 0.50 tier
    cancelled = validate_success(
        api.cancel_booking(booking["id"], {"reason": "x"},
                           make_guest_headers(guest["id"])), 200)
    assert cancelled["refund_cents"] == 2500, cancelled["refund_cents"]
    assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"


# ─── Corner: calculations / refund 7-day half tier ────────────────────

def test_refund_7_days_half_refund(api):
    """PRD §3.6: "if it is at least 7 but fewer than 14, the rate is 0.50. ... The money dimension
    then moves payment_status to REFUNDED when the refund equals the full deposit_paid_cents, and
    to PARTIALLY_REFUNDED when the refund is smaller than what was paid."

    Design: Corner/calculations/refund_tier_7_day_half_refund
    """
    _ctx, guest, booking = provision_confirmed_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25,
        event_overrides={"event_start": "2026-03-15T00:00:00Z",
                         "event_end": "2026-03-15T04:00:00Z"})
    set_clock("2026-03-08T00:00:00Z")  # exactly 7 days out -> 0.50
    cancelled = validate_success(
        api.cancel_booking(booking["id"], {"reason": "half"},
                           make_guest_headers(guest["id"])), 200)
    assert cancelled["refund_cents"] == 2500, cancelled["refund_cents"]
    assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"


# ─── Difficulty: compensating_invariant / seat-count conservation ─────

def test_book_then_cancel_restores_available_seats(api):
    """PRD §3.6: "Every seat the booking held transitions BOOKED → AVAILABLE with
    current_booking_id cleared."
    PRD §3.8: "available_seat_count is the number whose status is AVAILABLE".

    Design: Difficulty/compensating_invariant/seat_count_conservation_book_then_cancel
    """
    ctx, guest, booking = provision_confirmed_booking(
        seat_count=1, event_overrides={"seat_capacity": 3})
    validate_success(api.cancel_booking(booking["id"], {"reason": "test"},
                                        make_guest_headers(guest["id"])), 200)
    event = get_event(ctx["event"]["id"])
    assert event["available_seat_count"] == 3, event["available_seat_count"]


def test_book_then_cancel_leaves_zero_confirmed_seats(api):
    """PRD §3.8: "confirmed_seat_count is the number of the event's seats whose status is BOOKED".

    Design: Difficulty/compensating_invariant/seat_count_conservation_book_then_cancel
    """
    ctx, guest, booking = provision_confirmed_booking(
        seat_count=1, event_overrides={"seat_capacity": 3})
    validate_success(api.cancel_booking(booking["id"], {"reason": "test"},
                                        make_guest_headers(guest["id"])), 200)
    event = get_event(ctx["event"]["id"])
    assert event["confirmed_seat_count"] == 0, event["confirmed_seat_count"]


# ─── Difficulty: compensating_invariant / money conservation ──────────

def test_full_refund_leaves_paid_and_refund_equal(api):
    """PRD §3.6: "The refund_cents is deposit_paid_cents multiplied by that rate, rounded to whole
    cents using round half up."

    Design: Difficulty/compensating_invariant/deposit_money_conservation_book_then_refund
    """
    _ctx, guest, booking = provision_confirmed_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25,
        event_overrides={"event_start": "2026-03-15T00:00:00Z",
                         "event_end": "2026-03-15T04:00:00Z"})
    cancelled = validate_success(
        api.cancel_booking(booking["id"], {"reason": "test"},
                           make_guest_headers(guest["id"])), 200)
    assert cancelled["deposit_paid_cents"] == 5000
    assert cancelled["refund_cents"] == 5000


def test_full_refund_zeroes_gross_deposit_held(api):
    """PRD §3.8: "gross_deposit_held_cents is the sum, across all of the event's bookings, of each
    booking's deposit_paid_cents minus its refund_cents."

    Design: Difficulty/compensating_invariant/deposit_money_conservation_book_then_refund
    """
    ctx, guest, booking = provision_confirmed_booking(
        seat_count=2, seat_price_cents=10000, deposit_pct=0.25,
        event_overrides={"event_start": "2026-03-15T00:00:00Z",
                         "event_end": "2026-03-15T04:00:00Z"})
    validate_success(api.cancel_booking(booking["id"], {"reason": "test"},
                                        make_guest_headers(guest["id"])), 200)
    event = get_event(ctx["event"]["id"])
    assert event["gross_deposit_held_cents"] == 0, event["gross_deposit_held_cents"]


# ─── Corner: state_machines / terminal-guard idempotency ──────────────

def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.6: "Cancellation is refused if the booking has already reached a terminal outcome —
    that is, if its booking_status is already ATTENDED, CANCELLED, or NO_SHOW — in which case the
    request fails with ERR_BOOKING_ALREADY_TERMINAL."

    Design: Corner/state_machines/cancel_already_cancelled_booking_rejected
    """
    _ctx, guest, booking = provision_confirmed_booking(seat_count=1)
    validate_success(api.cancel_booking(booking["id"], {"reason": "first"},
                                        make_guest_headers(guest["id"])), 200)
    res = api.cancel_booking(booking["id"], {"reason": "again"}, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_BOOKING_ALREADY_TERMINAL")


def test_withdraw_already_withdrawn_entry_rejected(api):
    """PRD §3.7: "Withdrawal is only legal while the entry is WAITING; against any other status it
    fails with ERR_WAITLIST_ENTRY_NOT_WAITING."

    Design: Corner/state_machines/withdraw_non_waiting_entry_rejected
    """
    ctx, _g1, _b1 = provision_confirmed_booking(seat_count=1)  # event full
    g2 = create_guest(email="g2@x.com")
    w2 = join_waitlist(ctx["event"]["id"], g2["id"], party_size=1)
    validate_success(api.withdraw_waitlist(w2["id"], make_guest_headers(g2["id"])), 200)
    res = api.withdraw_waitlist(w2["id"], make_guest_headers(g2["id"]))
    validate_error(res, "ERR_WAITLIST_ENTRY_NOT_WAITING")


# ─── Corner: validations / cannot join waitlist while seats free ──────

def test_join_waitlist_with_seats_available_rejected(api):
    """PRD §3.7: "only when the event is genuinely full, meaning its available_seat_count is 0;
    if any seat is still available the request is rejected with ERR_SEATS_AVAILABLE."

    Design: Corner/validations/join_waitlist_with_seats_available_returns_409
    """
    ctx = provision_open_event(event_overrides={"seat_capacity": 2})  # no seats booked
    guest = create_guest()
    res = api.join_waitlist(ctx["event"]["id"], {"guest_id": guest["id"], "party_size": 1},
                            make_guest_headers(guest["id"]))
    validate_error(res, "ERR_SEATS_AVAILABLE")


# ─── Difficulty: dual_variant_calc / projected vs realized revenue ────

def _two_confirmed_communal_event(api):
    ctx = provision_open_event(event_overrides={
        "seat_capacity": 2, "seat_price_cents": 10000, "table_mode": "COMMUNAL",
        "event_start": "2026-03-20T18:00:00Z", "event_end": "2026-03-20T22:00:00Z",
        "booking_deadline": "2026-03-19T00:00:00Z"})
    g1 = create_guest(email="g1@x.com")
    g2 = create_guest(email="g2@x.com")
    b1 = book_seats(ctx["event"]["id"], g1["id"], [ctx["seats"][0]["id"]], party_size=1)
    pay_deposit(b1["id"], g1["id"], b1["deposit_due_cents"])
    b2 = book_seats(ctx["event"]["id"], g2["id"], [ctx["seats"][1]["id"]], party_size=1)
    pay_deposit(b2["id"], g2["id"], b2["deposit_due_cents"])
    return ctx


def test_projected_revenue_counts_confirmed_full_totals(api):
    """PRD §3.8: "The forward-looking projected_revenue_cents sums total_price_cents across the
    event's bookings whose booking_status is PENDING_DEPOSIT or CONFIRMED — the reservations not
    yet resolved, counted at full price."

    Design: Difficulty/dual_variant_calc/projected_vs_realized_revenue_on_event
    """
    ctx = _two_confirmed_communal_event(api)
    event = get_event(ctx["event"]["id"])
    assert event["projected_revenue_cents"] == 20000, event["projected_revenue_cents"]


def test_realized_revenue_excludes_unattended_and_differs(api):
    """PRD §3.8: "The chronological realized_revenue_cents counts only settled outcomes: it sums
    total_price_cents over bookings whose booking_status is ATTENDED, plus deposit_paid_cents over
    bookings whose booking_status is NO_SHOW (the forfeited deposits), and excludes everything
    still pending."

    Design: Difficulty/dual_variant_calc/projected_vs_realized_revenue_on_event
    """
    ctx = _two_confirmed_communal_event(api)
    event = get_event(ctx["event"]["id"])
    assert event["realized_revenue_cents"] == 0, event["realized_revenue_cents"]
    assert event["projected_revenue_cents"] != event["realized_revenue_cents"]


# ─── Difficulty: non_linear_state_machine / parallel booking dimensions ─

def test_checkin_moves_booking_status_to_attended(api):
    """PRD §3.5: "At the door, a VenueManager checks a guest in, advancing the booking
    CONFIRMED → ATTENDED, which is terminal."

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_dimensions
    """
    _ctx, _guest, booking = provision_confirmed_booking(seat_count=1)
    attended = validate_success(api.check_in_booking(booking["id"], ADMIN), 200)
    assert attended["booking_status"] == "ATTENDED", attended["booking_status"]


def test_checkin_leaves_payment_status_deposit_paid(api):
    """PRD §3.5: "On success the money dimension advances payment_status from UNPAID →
    DEPOSIT_PAID".

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_dimensions
    """
    _ctx, _guest, booking = provision_confirmed_booking(seat_count=1)
    attended = validate_success(api.check_in_booking(booking["id"], ADMIN), 200)
    # The independent money dimension is untouched by check-in.
    assert attended["payment_status"] == "DEPOSIT_PAID", attended["payment_status"]


# ─── Corner: endpoints / payment ledger reverse-reachable ─────────────

def test_booking_payments_reverse_reachable(api):
    """PRD §3.5: "a Payment ledger entry is appended with kind of DEPOSIT, direction of CHARGE,
    the paid amount_cents, and an optional reason."

    Design: Corner/endpoints/booking_payments_reverse_reachable
    """
    _ctx, _guest, booking = provision_confirmed_booking(
        seat_count=1, seat_price_cents=10000, deposit_pct=0.25)
    payments = get_booking_payments(booking["id"])
    assert len(payments) == 1, payments
    assert payments[0]["kind"] == "DEPOSIT"
    assert payments[0]["amount_cents"] == 2500, payments[0]["amount_cents"]
