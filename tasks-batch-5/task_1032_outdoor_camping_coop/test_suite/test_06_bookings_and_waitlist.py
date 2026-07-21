"""Bookings, the waitlist promotion cascade, seat/credit conservation, member
schedule overlap, trip-state dependency, priority ordering, and trip-level cascades.

Queue-A depth: transitive_cascade, boundary_precision_check, compensating_invariant
(x2), resource_temporal_overlap (member schedule), cross_entity_state_dependency,
priority_pair_validation_conflict. Queue-B: membership-inactive, trip cancel cascade,
trip complete no-show.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_member, new_class_trip, book, cancel_booking, cancel_trip, complete_trip,
    get_trip, setup_trip_with_booked_and_waitlisted, assert_seats_conserved,
    create_booking_payload, make_member_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def _book_expecting_error(api, member, trip):
    version = get_trip(trip["id"])["version"]
    payload = create_booking_payload(member["id"], trip["id"], version)
    return api.create_booking(payload, make_member_headers(member["id"]))


# ─── transitive_cascade / booking_cancel_promotes_waitlist... ──────────────

def test_cancel_promotes_earliest_waitlisted(api):
    """PRD §3.5: "the earliest WAITLISTED booking on the same trip by created_at
    ascending is promoted to BOOKED: that promoted booking sets booked_from_waitlist
    to true, increases seats_reserved by one, decreases waitlist_count by one, sets
    its price_paid_cents to the trip's price_cents, and debits that price from the
    promoted member's store_credit_cents."

    Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_and_debits_promoted_member
    """
    trip, ma, ba, _mb, bb = setup_trip_with_booked_and_waitlisted(price_cents=3000, credit=5000)
    cancel_booking(ma, ba["id"])
    bb_after = validate_success(api.get_booking(bb["id"], STAFF), 200)
    assert bb_after["status"] == "BOOKED"
    assert bb_after["booked_from_waitlist"] is True


def test_promotion_debits_promoted_member(api):
    """PRD §3.5: "sets its price_paid_cents to the trip's price_cents, and debits
    that price from the promoted member's store_credit_cents."
    PRD §3.5: "Cancellation moves the booking to CANCELLED and refunds price_paid_cents
    to the member's store_credit_cents".

    Design: Difficulty/transitive_cascade/booking_cancel_promotes_waitlist_and_debits_promoted_member
    """
    trip, ma, ba, mb, _bb = setup_trip_with_booked_and_waitlisted(price_cents=3000, credit=5000)
    cancel_booking(ma, ba["id"])
    mb_after = validate_success(api.get_member(mb["id"], STAFF), 200)
    ma_after = validate_success(api.get_member(ma["id"], STAFF), 200)
    trip_after = validate_success(api.get_class_trip(trip["id"], STAFF), 200)
    assert mb_after["store_credit_cents"] == 2000   # 5000 - 3000 (charged on promotion)
    assert ma_after["store_credit_cents"] == 5000   # debited 3000, refunded 3000 on cancel
    assert trip_after["seats_reserved"] == 1


# ─── boundary_precision_check / booking_capacity_zero_seats_waitlists ──────

def test_first_booking_takes_seat(api):
    """PRD §3.5: "when seats_available is at least one the booking is created BOOKED,
    and when seats_available is zero it is created WAITLISTED."

    Design: Difficulty/boundary_precision_check/booking_capacity_zero_seats_waitlists
    """
    _trip, _ma, ba, _mb, _bb = setup_trip_with_booked_and_waitlisted(price_cents=3000, credit=5000)
    assert ba["status"] == "BOOKED"


def test_second_booking_waitlists_at_zero_seats(api):
    """PRD §3.5: "Whether a create seats or waitlists is not an error either way:
    when seats_available is at least one the booking is created BOOKED, and when
    seats_available is zero it is created WAITLISTED."

    Design: Difficulty/boundary_precision_check/booking_capacity_zero_seats_waitlists
    """
    trip, _ma, _ba, _mb, bb = setup_trip_with_booked_and_waitlisted(price_cents=3000, credit=5000)
    assert bb["status"] == "WAITLISTED"
    trip_after = validate_success(api.get_class_trip(trip["id"], STAFF), 200)
    assert trip_after["seats_available"] == 0


# ─── compensating_invariant / store_credit_conserved_on_booking_book_then_cancel

def test_book_debits_store_credit(api):
    """PRD §3.5: "A BOOKED create increments seats_reserved, sets price_paid_cents to
    the trip's price_cents, and debits that amount from the member's
    store_credit_cents."

    Design: Difficulty/compensating_invariant/store_credit_conserved_on_booking_book_then_cancel
    """
    member = new_member(credit=3000)
    trip = new_class_trip(capacity=5, price_cents=3000,
                          start_at="2026-07-30T08:00:00Z", end_at="2026-07-30T16:00:00Z")
    book(member, trip)
    m_after = validate_success(api.get_member(member["id"], STAFF), 200)
    assert m_after["store_credit_cents"] == 0


def test_cancel_refunds_store_credit_conserved(api):
    """PRD §3.5: "Cancellation moves the booking to CANCELLED and refunds
    price_paid_cents to the member's store_credit_cents — which is zero for a
    waitlisted booking."

    Book debits 3000, cancel refunds 3000, so store_credit returns to 3000.

    Design: Difficulty/compensating_invariant/store_credit_conserved_on_booking_book_then_cancel
    """
    member = new_member(credit=3000)
    trip = new_class_trip(capacity=5, price_cents=3000,
                          start_at="2026-07-30T08:00:00Z", end_at="2026-07-30T16:00:00Z")
    b = book(member, trip)
    cancel_booking(member, b["id"])
    m_after = validate_success(api.get_member(member["id"], STAFF), 200)
    booking_after = validate_success(api.get_booking(b["id"], STAFF), 200)
    assert m_after["store_credit_cents"] == 3000
    assert booking_after["status"] == "CANCELLED"


# ─── compensating_invariant / seats_conserved_on_booking_book_then_cancel ──

def test_book_reserves_seat(api):
    """PRD §3.5: "seats_reserved is the number of bookings in BOOKED or CHECKED_IN,
    seats_available is the capacity minus seats_reserved floored at zero".

    Design: Difficulty/compensating_invariant/seats_conserved_on_booking_book_then_cancel
    """
    member = new_member(credit=5000)
    trip = new_class_trip(capacity=2, price_cents=1000,
                          start_at="2026-08-02T08:00:00Z", end_at="2026-08-02T11:00:00Z")
    book(member, trip)
    trip_after = validate_success(api.get_class_trip(trip["id"], STAFF), 200)
    assert trip_after["seats_reserved"] == 1
    assert trip_after["seats_available"] == 1
    assert_seats_conserved(trip_after)


def test_cancel_releases_seat_invariant(api):
    """PRD §3.5: "If the cancelled booking had been BOOKED, its seat is released,
    seats_reserved drops by one".
    PRD §3.5: "seats_available is the capacity minus seats_reserved floored at zero".

    Design: Difficulty/compensating_invariant/seats_conserved_on_booking_book_then_cancel
    """
    member = new_member(credit=5000)
    trip = new_class_trip(capacity=2, price_cents=1000,
                          start_at="2026-08-02T08:00:00Z", end_at="2026-08-02T11:00:00Z")
    b = book(member, trip)
    cancel_booking(member, b["id"])
    trip_after = validate_success(api.get_class_trip(trip["id"], STAFF), 200)
    assert trip_after["seats_reserved"] == 0
    assert trip_after["seats_available"] == 2
    assert_seats_conserved(trip_after)


# ─── resource_temporal_overlap / member_booking_overlap_closed_interval ────

def test_member_overlapping_trip_booking_rejected(api):
    """PRD §3.5: "The schedule check rejects the booking with
    ERR_MEMBER_SCHEDULE_CONFLICT when the member already holds another non-terminal
    booking on a trip whose closed interval from start_at to end_at — inclusive of
    both endpoints — overlaps this trip."

    Trip2 [11:00,15:00] strictly overlaps the member's trip1 [08:00,12:00] booking.

    Design: Difficulty/resource_temporal_overlap/member_booking_overlap_closed_interval
    """
    member = new_member(credit=5000)
    trip1 = new_class_trip(capacity=5, price_cents=1000, title="Rock 1",
                           start_at="2026-07-20T08:00:00Z", end_at="2026-07-20T12:00:00Z")
    trip2 = new_class_trip(capacity=5, price_cents=1000, title="Rock 2",
                           start_at="2026-07-20T11:00:00Z", end_at="2026-07-20T15:00:00Z")
    book(member, trip1)
    res = _book_expecting_error(api, member, trip2)
    validate_error(res, ApiErrorId.ERR_MEMBER_SCHEDULE_CONFLICT.value)


def test_member_schedule_shared_endpoint_conflict(api):
    """PRD §3.5: "a trip whose closed interval from start_at to end_at — inclusive of
    both endpoints — overlaps this trip."

    Trip3 [12:00,16:00] shares the endpoint 12:00 with trip1 [08:00,12:00]; closed
    intervals sharing an endpoint overlap, so the booking is rejected.

    Design: Difficulty/resource_temporal_overlap/member_booking_overlap_closed_interval
    """
    member = new_member(credit=5000)
    trip1 = new_class_trip(capacity=5, price_cents=1000, title="Rock 1",
                           start_at="2026-07-20T08:00:00Z", end_at="2026-07-20T12:00:00Z")
    trip3 = new_class_trip(capacity=5, price_cents=1000, title="Rock 3",
                           start_at="2026-07-20T12:00:00Z", end_at="2026-07-20T16:00:00Z")
    book(member, trip1)
    res = _book_expecting_error(api, member, trip3)
    validate_error(res, ApiErrorId.ERR_MEMBER_SCHEDULE_CONFLICT.value)


# ─── cross_entity_state_dependency / booking_requires_trip_scheduled ───────

def test_booking_on_cancelled_trip_rejected(api):
    """PRD §3.5: "a booking against a non-scheduled trip is rejected with
    ERR_TRIP_NOT_SCHEDULED".

    Design: Difficulty/cross_entity_state_dependency/booking_requires_trip_scheduled
    """
    member = new_member(credit=5000)
    trip = new_class_trip(capacity=5, price_cents=1000, title="Nav Basics",
                          start_at="2026-07-28T08:00:00Z", end_at="2026-07-28T10:00:00Z")
    cancel_trip(trip["id"])
    res = _book_expecting_error(api, member, trip)
    validate_error(res, ApiErrorId.ERR_TRIP_NOT_SCHEDULED.value)


def test_cancelled_trip_status_blocks_booking(api):
    """PRD §3.5: "Cancelling a trip is allowed only while it is SCHEDULED and moves
    it to CANCELLED".
    PRD §3.5: "a booking against a non-scheduled trip is rejected with
    ERR_TRIP_NOT_SCHEDULED".

    Design: Difficulty/cross_entity_state_dependency/booking_requires_trip_scheduled
    """
    member = new_member(credit=5000)
    trip = new_class_trip(capacity=5, price_cents=1000, title="Nav Basics",
                          start_at="2026-07-28T08:00:00Z", end_at="2026-07-28T10:00:00Z")
    cancelled = cancel_trip(trip["id"])
    assert cancelled["status"] == "CANCELLED"
    res = _book_expecting_error(api, member, trip)
    validate_error(res, ApiErrorId.ERR_TRIP_NOT_SCHEDULED.value)


# ─── priority_pair / state_beats_fiscal_on_booking_completed_trip ──────────

def test_booking_on_completed_trip_returns_state_error(api):
    """PRD §3.5: "Completing a trip is allowed only while it is SCHEDULED and moves
    it to COMPLETED".
    PRD §3.5: "a booking against a non-scheduled trip is rejected with
    ERR_TRIP_NOT_SCHEDULED".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_completed_trip
    """
    member = new_member(credit=0)
    trip = new_class_trip(capacity=5, price_cents=3000, title="Map & Compass",
                          start_at="2026-07-22T08:00:00Z", end_at="2026-07-22T10:00:00Z")
    complete_trip(trip["id"])
    res = _book_expecting_error(api, member, trip)
    validate_error(res, ApiErrorId.ERR_TRIP_NOT_SCHEDULED.value)


def test_state_beats_fiscal_zero_credit_member(api):
    """PRD §2.10: "then whether the target resource is in a legal state for the
    requested transition (priority 4). Business rules follow in this order:
    membership-active safety checks (priority 5), temporal-window checks (priority 6),
    the rental rentability referential check (priority 7), the permit quota-capacity
    check (priority 8), and the store-credit sufficiency fiscal check (priority 9)."

    A 0-credit member booking a COMPLETED trip receives the state error (priority 4),
    not the fiscal ERR_INSUFFICIENT_STORE_CREDIT (priority 9).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_booking_completed_trip
    """
    member = new_member(credit=0)
    trip = new_class_trip(capacity=5, price_cents=3000, title="Map & Compass",
                          start_at="2026-07-22T08:00:00Z", end_at="2026-07-22T10:00:00Z")
    complete_trip(trip["id"])
    res = _book_expecting_error(api, member, trip)
    body = res.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_TRIP_NOT_SCHEDULED.value
    assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value


# ─── Queue-B validations / booking_rejected_when_membership_inactive ───────

def test_booking_rejected_when_membership_inactive(api):
    """PRD §3.5: "to the member's membership_status being ACTIVE (else
    ERR_MEMBERSHIP_INACTIVE)".

    Design: Corner/validations/booking_rejected_when_membership_inactive
    """
    member = new_member(status="LAPSED", credit=5000)
    trip = new_class_trip(capacity=3, price_cents=1000, title="Va Trip",
                          start_at="2026-08-10T08:00:00Z", end_at="2026-08-10T10:00:00Z")
    res = _book_expecting_error(api, member, trip)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_INACTIVE.value)


# ─── Queue-B state_machines / classtrip_cancel_cascades_bookings_to_cancelled

def test_classtrip_cancel_cascades_bookings_to_cancelled(api):
    """PRD §3.5: "every booking still in BOOKED, WAITLISTED, or CHECKED_IN is
    cascaded to CANCELLED, each such cancellation refunds that booking's
    price_paid_cents to its member and reverses any loyalty earned at check-in".

    Design: Corner/state_machines/classtrip_cancel_cascades_bookings_to_cancelled
    """
    member = new_member(credit=1000)
    trip = new_class_trip(capacity=3, price_cents=1000, title="Cascade Trip",
                          start_at="2026-08-08T08:00:00Z", end_at="2026-08-08T10:00:00Z")
    b = book(member, trip)
    cancelled_trip = cancel_trip(trip["id"])
    booking_after = validate_success(api.get_booking(b["id"], STAFF), 200)
    m_after = validate_success(api.get_member(member["id"], STAFF), 200)
    assert booking_after["status"] == "CANCELLED"
    assert m_after["store_credit_cents"] == 1000
    assert cancelled_trip["status"] == "CANCELLED"


# ─── Queue-B state_machines / classtrip_complete_marks_booked_as_no_show ───

def test_classtrip_complete_marks_booked_as_no_show(api):
    """PRD §3.5: "every booking still merely BOOKED becomes NO_SHOW with no refund,
    while CHECKED_IN bookings remain as they are."

    Design: Corner/state_machines/classtrip_complete_marks_booked_as_no_show
    """
    member = new_member(credit=2000)
    trip = new_class_trip(capacity=3, price_cents=2000, title="NoShow Trip",
                          start_at="2026-08-09T08:00:00Z", end_at="2026-08-09T10:00:00Z")
    b = book(member, trip)
    complete_trip(trip["id"])
    booking_after = validate_success(api.get_booking(b["id"], STAFF), 200)
    m_after = validate_success(api.get_member(member["id"], STAFF), 200)
    assert booking_after["status"] == "NO_SHOW"
    assert m_after["store_credit_cents"] == 0
