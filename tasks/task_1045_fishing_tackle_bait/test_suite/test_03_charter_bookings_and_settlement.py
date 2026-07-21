"""Charter bookings: provisional vs final settlement, independent payment/attendance
dimensions, seat-capacity boundary, state-vs-capacity precedence, refunds, and the
suspended-customer / payment-required / terminal guards.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, new_customer, new_license_type, issue_license, new_guide, new_charter,
    new_booking, make_customer_at_tier, create_paid_booking, create_completed_booking,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _licensed_customer(dob="1985-01-01", tier=None):
    if tier:
        cust = make_customer_at_tier(tier, date_of_birth=dob)
    else:
        cust = new_customer(date_of_birth=dob)
    lt = new_license_type()
    issue_license(cust["id"], lt["id"])
    return cust


# ─── Difficulty: dual_variant_calc / charter_settlement_provisional_vs_final_gold_discount
def test_provisional_total_is_gross_seat_and_fuel(api):
    """PRD §3.5: "At create time the booking's provisional_total_cents is pinned: it is the
    gross seat charge, namely the requested seats multiplied by the charter's
    price_per_seat_cents, plus the requested seats multiplied by the charter's
    fuel_surcharge_cents. The provisional total carries no loyalty discount."

    Design: Difficulty/dual_variant_calc/charter_settlement_provisional_vs_final_gold_discount
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer(dob="1980-01-01", tier="GOLD")
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-01T09:00:00Z",
                          end_at="2026-08-01T12:00:00Z", capacity=6,
                          price_per_seat_cents=15000, fuel_surcharge_cents=2000)
    booking = new_booking(charter["id"], cust["id"], seats=2)
    assert booking["provisional_total_cents"] == 34000  # 2*15000 + 2*2000


def test_final_total_applies_gold_discount_and_diverges(api):
    """PRD §3.5: "Completion pins the booking's final_total_cents using the final settlement
    variant: the same gross seat-and-fuel charge as the provisional total, but multiplied by
    one minus the customer's tier discount, then rounded half up to whole cents. The tier
    discount is 0% for BRONZE, 5% for SILVER, and 10% for GOLD, so the final total diverges
    from the provisional total precisely when the customer is not BRONZE."

    Design: Difficulty/dual_variant_calc/charter_settlement_provisional_vs_final_gold_discount
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer(dob="1980-01-01", tier="GOLD")
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-01T09:00:00Z",
                          end_at="2026-08-01T12:00:00Z", capacity=6,
                          price_per_seat_cents=15000, fuel_surcharge_cents=2000)
    completed = create_completed_booking(charter["id"], cust["id"], seats=2)
    assert completed["final_total_cents"] == 30600  # round(34000 * 0.90)
    assert completed["provisional_total_cents"] == 34000
    assert completed["final_total_cents"] != completed["provisional_total_cents"]


# ─── Difficulty: non_linear_state_machine / charter_booking_payment_and_attendance_dimensions_independent
def test_pay_advances_payment_dimension(api):
    """PRD §3.5: "An angler or clerk pays a booking, moving the payment dimension
    UNPAID → PAID."

    Design: Difficulty/non_linear_state_machine/charter_booking_payment_and_attendance_dimensions_independent
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-02T09:00:00Z",
                          end_at="2026-08-02T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    booking = new_booking(charter["id"], cust["id"], seats=1)
    paid = validate_success(api.pay_booking(booking["id"], CLERK), 200)
    assert paid["payment_status"] == "PAID"


def test_pay_leaves_attendance_dimension_reserved(api):
    """PRD §3.5: "A booking carries two **independent** status dimensions that evolve
    separately: an attendance `booking_status` (`RESERVED`, `WAITLISTED`, `CHECKED_IN`,
    `COMPLETED`, or `CANCELLED`) and a `payment_status` (`UNPAID`, `PAID`, or `REFUNDED`)."

    Design: Difficulty/non_linear_state_machine/charter_booking_payment_and_attendance_dimensions_independent
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-02T09:00:00Z",
                          end_at="2026-08-02T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    booking = new_booking(charter["id"], cust["id"], seats=1)
    paid = validate_success(api.pay_booking(booking["id"], CLERK), 200)
    assert paid["booking_status"] == "RESERVED"  # attendance did not auto-advance


# ─── Difficulty: boundary_precision_check / charter_seats_request_equals_remaining_ok_over_by_one_fails
def test_seats_equal_remaining_accepted_fills_charter(api):
    """PRD §3.5: "the requested seats must be at most the remaining capacity (capacity minus
    booked_seats)."
    PRD §3.4: "it flips `OPEN → FULL` the moment booked seats reach capacity"

    Design: Difficulty/boundary_precision_check/charter_seats_request_equals_remaining_ok_over_by_one_fails
    """
    set_clock("2026-07-15T00:00:00Z")
    a = _licensed_customer(dob="1985-01-01")
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-15T09:00:00Z",
                          end_at="2026-08-15T12:00:00Z", capacity=3, price_per_seat_cents=10000)
    booking = new_booking(charter["id"], a["id"], seats=3)
    assert booking["seats"] == 3
    refreshed = get_success_data(api.get_charter(charter["id"], CLERK))
    assert refreshed["status"] == "FULL"


def test_seats_over_remaining_by_one_rejected(api):
    """PRD §3.5: "If they exceed it and `waitlist_requested` is false, the booking is refused
    with `ERR_INSUFFICIENT_SEATS` (HTTP 409)"

    Design: Difficulty/boundary_precision_check/charter_seats_request_equals_remaining_ok_over_by_one_fails
    """
    set_clock("2026-07-15T00:00:00Z")
    a = _licensed_customer(dob="1985-01-01")
    b = _licensed_customer(dob="1986-01-01")
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-15T09:00:00Z",
                          end_at="2026-08-15T12:00:00Z", capacity=3, price_per_seat_cents=10000)
    new_booking(charter["id"], a["id"], seats=3)  # fills to FULL
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": b["id"], "seats": 1}, CLERK)
    validate_error(res, "ERR_INSUFFICIENT_SEATS", 409)


# ─── Difficulty: priority_pair_validation_conflict / booking_state_beats_seat_capacity
def test_charter_state_error_beats_seat_capacity(api):
    """PRD §2.9: "the checks are evaluated in a fixed priority order so that the returned
    error is deterministic."
    PRD §3.5: "The target charter must be `OPEN` or `FULL`; a booking against a cancelled
    charter is refused with `ERR_CHARTER_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_seat_capacity
    """
    set_clock("2026-07-15T00:00:00Z")
    b = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-10T09:00:00Z",
                          end_at="2026-08-10T12:00:00Z", capacity=1, price_per_seat_cents=10000)
    validate_success(api.cancel_charter(charter["id"], MANAGER), 200)
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": b["id"], "seats": 5}, CLERK)
    validate_error(res, "ERR_CHARTER_NOT_OPEN", 409)


def test_cancelled_charter_unchanged_after_rejected_overbooking(api):
    """PRD §3.4: "A new charter opens with `status` `OPEN` and `booked_seats` at zero"
    PRD §3.5: "The target charter must be `OPEN` or `FULL`; a booking against a cancelled
    charter is refused with `ERR_CHARTER_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_seat_capacity
    """
    set_clock("2026-07-15T00:00:00Z")
    b = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-10T09:00:00Z",
                          end_at="2026-08-10T12:00:00Z", capacity=1, price_per_seat_cents=10000)
    validate_success(api.cancel_charter(charter["id"], MANAGER), 200)
    api.create_booking({"charter_id": charter["id"], "customer_id": b["id"], "seats": 5}, CLERK)
    refreshed = get_success_data(api.get_charter(charter["id"], CLERK))
    assert refreshed["status"] == "CANCELLED"
    assert refreshed["booked_seats"] == 0


# ─── Corner: state_machines / checkin_without_payment_returns_payment_required
def test_checkin_unpaid_booking_rejected(api):
    """PRD §3.5: "Check-in requires that the booking is already `PAID` — an unpaid booking is
    refused with `ERR_PAYMENT_REQUIRED` — and that the charter is still `OPEN` or `FULL`
    rather than cancelled."

    Design: Corner/state_machines/checkin_without_payment_returns_payment_required
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-03T09:00:00Z",
                          end_at="2026-08-03T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    booking = new_booking(charter["id"], cust["id"], seats=1)
    res = api.checkin_booking(booking["id"], CLERK)
    validate_error(res, "ERR_PAYMENT_REQUIRED", 409)


# ─── Corner: state_machines / customer_initiated_cancel_partial_refund_within_48h
def test_customer_cancel_within_48h_half_refund(api):
    """PRD §3.6: "if it is greater than zero but less than 48 hours, the refund is
    amount_paid_cents multiplied by 50%, rounded half up to whole cents"
    PRD §3.6: "Whenever a booking that is PAID is cancelled, a refund is computed,
    refund_amount_cents is set, and the payment dimension moves PAID → REFUNDED."

    Design: Corner/state_machines/customer_initiated_cancel_partial_refund_within_48h
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-02T09:00:00Z",
                          end_at="2026-08-02T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    booking = create_paid_booking(charter["id"], cust["id"], seats=1)  # paid 10000
    set_clock("2026-08-01T09:00:00Z")  # 24h before start (< 48h, > 0)
    cancelled = validate_success(api.cancel_booking(booking["id"], CLERK), 200)
    assert cancelled["refund_amount_cents"] == 5000
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["booking_status"] == "CANCELLED"


# ─── Corner: state_machines / terminal_completed_booking_cannot_cancel
def test_cancel_completed_booking_rejected(api):
    """PRD §2.9: "the target resource must be in a legal state for the requested transition,
    otherwise the transition-specific state error applies"
    PRD §2.9: "The state-tier error is `ERR_INVALID_STATE` (409) in the general case, but
    several transitions carry a more specific state error"

    Design: Corner/state_machines/terminal_completed_booking_cannot_cancel
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-04T09:00:00Z",
                          end_at="2026-08-04T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    booking = create_completed_booking(charter["id"], cust["id"], seats=1)
    res = api.cancel_booking(booking["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ─── Corner: consistency_model / booking_create_immediately_reflects_provisional_total
def test_booking_create_returns_provisional_total(api):
    """PRD §3.5: "At create time the booking's provisional_total_cents is pinned: it is the
    gross seat charge, namely the requested seats multiplied by the charter's
    price_per_seat_cents, plus the requested seats multiplied by the charter's
    fuel_surcharge_cents."

    Design: Corner/consistency_model/booking_create_immediately_reflects_provisional_total
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-11T09:00:00Z",
                          end_at="2026-08-11T12:00:00Z", capacity=4,
                          price_per_seat_cents=12000, fuel_surcharge_cents=1000)
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": cust["id"], "seats": 1}, CLERK)
    booking = validate_success(res, 201)
    assert booking["provisional_total_cents"] == 13000  # 1*12000 + 1*1000


# ─── Corner: validations / suspended_customer_cannot_book
def test_suspended_customer_cannot_book(api):
    """PRD §3.1: "While a customer is SUSPENDED, any attempt by or for them to book a charter
    or make a purchase is refused with ERR_CUSTOMER_SUSPENDED."

    Design: Corner/validations/suspended_customer_cannot_book
    """
    set_clock("2026-07-15T00:00:00Z")
    cust = _licensed_customer()
    validate_success(api.set_customer_status(cust["id"], {"status": "SUSPENDED"}, MANAGER), 200)
    guide = new_guide()
    charter = new_charter(guide["id"], start_at="2026-08-06T09:00:00Z",
                          end_at="2026-08-06T12:00:00Z", capacity=4, price_per_seat_cents=10000)
    res = api.create_booking(
        {"charter_id": charter["id"], "customer_id": cust["id"], "seats": 1}, CLERK)
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", 409)
