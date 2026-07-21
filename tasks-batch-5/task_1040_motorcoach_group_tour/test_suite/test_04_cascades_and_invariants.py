"""Transitive cancellation cascades and compensating-action conservation invariants."""
from test_helpers import (
    validate_success, ApiErrorId,
    setup_open_departure, add_confirmed_booking,
    get_departure, first_voucher_id,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Depth-3 cascade: Departure cancel -> Booking cancel -> Voucher void
# ---------------------------------------------------------------------------

def test_departure_cancel_cascades_to_booking(api, ops_headers):
    """PRD §3.8: "An OpsManager may cancel an entire departure while it is OPEN or
    GUARANTEED, moving it to the terminal CANCELLED state with a full cascade. Every
    non-terminal booking on the departure is cancelled as an operator cancellation with no
    penalty."

    Design: Difficulty/transitive_cascade/departure_cancel_cascades_booking_then_voucher_depth3
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    validate_success(api.cancel_departure(dep_id, {"reason": "operator cancel"}, ops_headers))
    dep = get_departure(dep_id)
    booking = validate_success(api.get_booking(bk["id"], ops_headers))
    assert dep["status"] == "CANCELLED", f"expected departure CANCELLED, got {dep['status']}"
    assert booking["reservation_status"] == "CANCELLED", \
        f"expected booking CANCELLED, got {booking['reservation_status']}"


def test_departure_cancel_cascades_to_voucher_void(api, ops_headers):
    """PRD §3.8: "Each such cancelled booking has its ISSUED vouchers set to VOIDED and
    receives a REFUND payment for its full amount_paid_cents, with its payment_status
    moving to REFUNDED."

    Design: Difficulty/transitive_cascade/departure_cancel_cascades_booking_then_voucher_depth3
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    vid = first_voucher_id(bk["id"])
    validate_success(api.cancel_departure(dep_id, {"reason": "operator cancel"}, ops_headers))
    voucher = validate_success(api.get_voucher(vid, ops_headers))
    assert voucher["status"] == "VOIDED", f"expected voucher VOIDED, got {voucher['status']}"


# ---------------------------------------------------------------------------
# Depth-2 cascade: Booking cancel -> Passenger seat cleared -> confirmed_pax down
# ---------------------------------------------------------------------------

def test_booking_cancel_clears_passenger_seat(api, sales_headers):
    """PRD §3.8: "Cancelling a confirmed booking also unwinds its operational footprint:
    every passenger on the booking has its seat_no and room_no cleared, the departure's
    confirmed_pax is reduced by the booking's pax_count"

    Design: Difficulty/transitive_cascade/booking_cancel_releases_passenger_seat_then_confirmed_pax_depth2
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = fx.create_booking(dep_id, pax_count=2, rooms_requested=0)
    pax1 = fx.add_passenger(bk["id"], full_name="I1", is_lead=True)
    fx.add_passenger(bk["id"], full_name="I2")
    fx.pay(bk["id"], "DEPOSIT", bk["deposit_due_cents"])
    fx.confirm_booking(bk["id"])
    validate_success(api.cancel_booking(bk["id"], {"reason": "released"}, sales_headers))
    passenger = validate_success(api.get_passenger(pax1["id"], sales_headers))
    assert passenger["seat_no"] is None, f"expected seat_no cleared, got {passenger['seat_no']}"


def test_booking_cancel_recomputes_confirmed_pax(api, sales_headers):
    """PRD §3.8: "the departure's confirmed_pax is reduced by the booking's pax_count"
    PRD §2.7: "A departure's confirmed_pax is always the sum of pax_count over the bookings
    on that departure whose reservation_status is CONFIRMED or TRAVELED."

    Design: Difficulty/transitive_cascade/booking_cancel_releases_passenger_seat_then_confirmed_pax_depth2
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    validate_success(api.cancel_booking(bk["id"], {"reason": "released"}, sales_headers))
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 0, f"expected confirmed_pax 0, got {dep['confirmed_pax']}"


# ---------------------------------------------------------------------------
# Conserved seat occupancy: confirm(+2) then cancel(-2) leaves confirmed_pax unchanged
# ---------------------------------------------------------------------------

def test_seat_occupancy_returns_to_zero_after_confirm_then_cancel(api, sales_headers):
    """PRD §2.7: "These are recomputed whenever a booking is confirmed or cancelled and
    whenever a departure is cancelled, so that a forward action and its later compensating
    action leave the totals unchanged."

    Design: Difficulty/compensating_invariant/seat_occupancy_conserved_confirm_then_cancel
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    validate_success(api.cancel_booking(bk["id"], {"reason": "compensate"}, sales_headers))
    dep = get_departure(dep_id)
    assert dep["confirmed_pax"] == 0, \
        f"seat occupancy not conserved: expected 0, got {dep['confirmed_pax']}"


def test_booking_cancel_does_not_release_the_coach(api, sales_headers):
    """PRD §2.7: "Coaches, drivers, and guides are returned to the pool (their status set
    back to AVAILABLE) whenever the departure that held them is settled or cancelled, or
    when a reassignment supersedes them."

    Design: Difficulty/compensating_invariant/seat_occupancy_conserved_confirm_then_cancel
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=5)
    dep_id = s["dep"]["id"]
    coach_id = s["coach"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0)
    validate_success(api.cancel_booking(bk["id"], {"reason": "compensate"}, sales_headers))
    coach = validate_success(api.get_coach(coach_id, sales_headers))
    # A booking cancel is not a departure settle/cancel/reassign, so the coach stays held.
    assert coach["status"] == "ASSIGNED", \
        f"coach should remain ASSIGNED after a booking cancel, got {coach['status']}"


# ---------------------------------------------------------------------------
# Conserved cash: operator cancel refunds in full (penalty 0)
# ---------------------------------------------------------------------------

def test_operator_cancel_refunds_full_amount_paid(api, ops_headers):
    """PRD §3.8: "Each such cancelled booking has its ISSUED vouchers set to VOIDED and
    receives a REFUND payment for its full amount_paid_cents, with its payment_status
    moving to REFUNDED."

    Design: Difficulty/compensating_invariant/cash_conserved_full_refund_on_operator_cancel
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2,
                             base_price=100000, deposit=20000, duration_days=2,
                             start_date="2026-08-25", end_date="2026-08-26")
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0, pay_full=True)
    validate_success(api.cancel_departure(dep_id, {"reason": "operator cancel full refund"}, ops_headers))
    booking = validate_success(api.get_booking(bk["id"], ops_headers))
    assert booking["amount_paid_cents"] == 257400, \
        f"expected amount_paid 257400, got {booking['amount_paid_cents']}"
    assert booking["amount_refunded_cents"] == 257400, \
        f"expected full refund 257400, got {booking['amount_refunded_cents']}"


def test_operator_cancel_charges_no_penalty(api, ops_headers):
    """PRD §3.8: "Every non-terminal booking on the departure is cancelled as an operator
    cancellation with no penalty."

    Design: Difficulty/compensating_invariant/cash_conserved_full_refund_on_operator_cancel
    """
    s = setup_open_departure(coach=True, seat_capacity=10, guaranteed_min_pax=2,
                             base_price=100000, deposit=20000, duration_days=2,
                             start_date="2026-08-25", end_date="2026-08-26")
    dep_id = s["dep"]["id"]
    bk = add_confirmed_booking(dep_id, pax_count=2, rooms_requested=0, pay_full=True)
    validate_success(api.cancel_departure(dep_id, {"reason": "operator cancel"}, ops_headers))
    booking = validate_success(api.get_booking(bk["id"], ops_headers))
    assert booking["penalty_charged_cents"] == 0, \
        f"operator cancel must charge no penalty, got {booking['penalty_charged_cents']}"
