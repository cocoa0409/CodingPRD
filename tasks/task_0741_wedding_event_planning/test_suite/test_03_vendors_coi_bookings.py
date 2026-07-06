"""Vendor insurance verification, the book precondition on a VERIFIED COI, and
booking / payment state-machine conflicts.

Covers queue A cross_entity_state_dependency (book requires verified COI) plus
queue B COI/booking/payment corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    PLANNER,
    create_event,
    create_vendor,
    create_coi,
    verify_coi,
    create_verified_vendor,
    create_pending_vendor,
    create_booking,
    setup_event_in_booking,
    setup_booked_booking,
    list_booking_payments,
)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency: book requires a VERIFIED COI
# ---------------------------------------------------------------------------
def test_book_with_pending_coi_rejected(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    The vendor's COI is still PENDING.

    Design: Difficulty/cross_entity_state_dependency/booking_book_requires_verified_coi
    """
    event, _contract = setup_event_in_booking(total_budget_cents=10_000_000)
    vendor, _coi = create_pending_vendor()
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=900_000)
    validate_error(
        api.book_vendor_booking(booking["id"], {"contracted_cost_cents": 1_000_000}, PLANNER),
        ApiErrorId.ERR_COI_NOT_VERIFIED.value,
    )


def test_book_succeeds_after_coi_verified(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    The positive complement: once the COI is VERIFIED the book is allowed.

    Design: Difficulty/cross_entity_state_dependency/booking_book_requires_verified_coi
    """
    event, _contract = setup_event_in_booking(total_budget_cents=10_000_000)
    vendor, coi = create_pending_vendor()
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=900_000)
    verify_coi(coi["id"])
    data = validate_success(
        api.book_vendor_booking(booking["id"], {"contracted_cost_cents": 1_000_000}, PLANNER)
    )
    assert data["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Queue B — COI verification conflicts
# ---------------------------------------------------------------------------
def test_verify_already_verified_coi_rejected(api):
    """PRD §3.2: "Verification requires the COI to be `PENDING` (otherwise
    `ERR_COI_NOT_PENDING`) and requires the `coverage_expiry_date` to be strictly after
    the current logical clock; a certificate whose `coverage_expiry_date` is at or before
    the current clock cannot be verified and the attempt is rejected with
    `ERR_COI_EXPIRED`."

    Design: Corner/state_machines/verify_coi_not_pending_returns_conflict
    """
    _vendor, coi = create_verified_vendor()
    validate_error(api.verify_coi(coi["id"], PLANNER), ApiErrorId.ERR_COI_NOT_PENDING.value)


def test_verify_expired_coi_rejected(api):
    """PRD §3.2: "Verification requires the COI to be `PENDING` (otherwise
    `ERR_COI_NOT_PENDING`) and requires the `coverage_expiry_date` to be strictly after
    the current logical clock; a certificate whose `coverage_expiry_date` is at or before
    the current clock cannot be verified and the attempt is rejected with
    `ERR_COI_EXPIRED`."

    The COI expires 2026-02-01 — before the startup clock 2026-03-01. No clock is set,
    so no sweep runs and the COI is still PENDING at verify time.

    Design: Corner/state_machines/verify_expired_coi_returns_422
    """
    vendor = create_vendor(category="FLORAL")
    coi = create_coi(vendor["id"], coverage_expiry_date="2026-02-01T00:00:00Z")
    validate_error(api.verify_coi(coi["id"], PLANNER), ApiErrorId.ERR_COI_EXPIRED.value)


# ---------------------------------------------------------------------------
# Queue B — booking / payment state-machine conflicts
# ---------------------------------------------------------------------------
def test_book_already_booked_rejected(api):
    """PRD §3.3: "Booking is guarded by several conditions evaluated in a fixed order:
    the booking must be in `PROPOSED` (otherwise `ERR_BOOKING_NOT_PROPOSED`) and its
    parent event must be in `BOOKING` (otherwise `ERR_EVENT_NOT_BOOKING`); then the
    referenced vendor must have a `VERIFIED` COI whose `coverage_expiry_date` is on or
    after the event's `event_date` (otherwise `ERR_COI_NOT_VERIFIED`); and finally,
    checked last, the fiscal guard must hold — the event's `committed_spend_cents` plus
    the new `contracted_cost_cents` must not exceed `total_budget_cents`, otherwise the
    booking is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/state_machines/book_already_booked_returns_not_proposed
    """
    _event, _vendor, booking = setup_booked_booking(contracted_cost_cents=1_000_000)
    validate_error(
        api.book_vendor_booking(booking["id"], {"contracted_cost_cents": 1_000_000}, PLANNER),
        ApiErrorId.ERR_BOOKING_NOT_PROPOSED.value,
    )


def test_pay_already_paid_rejected(api):
    """PRD §3.3: "The `Planner` pays a scheduled payment, moving it `SCHEDULED → PAID`
    and stamping `paid_at` with the current logical clock; a payment may be paid only
    from `SCHEDULED`, otherwise `ERR_PAYMENT_NOT_SCHEDULED`."

    Design: Corner/state_machines/pay_already_paid_returns_not_scheduled
    """
    _event, _vendor, booking = setup_booked_booking(contracted_cost_cents=2_000_000)
    payments = list_booking_payments(booking["id"])
    assert len(payments) == 2, "booking must mint a DEPOSIT and a BALANCE payment"
    first = payments[0]
    validate_success(api.pay_vendor_payment(first["id"], PLANNER))
    validate_error(
        api.pay_vendor_payment(first["id"], PLANNER), ApiErrorId.ERR_PAYMENT_NOT_SCHEDULED.value
    )


def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.3: "The `Planner` may cancel a booking that is in `PROPOSED` or `BOOKED`;
    any other state yields `ERR_BOOKING_NOT_CANCELLABLE`."

    Design: Corner/errors/cancel_already_cancelled_booking_returns_not_cancellable
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    vendor = create_vendor(category="OTHER")
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=100_000)
    validate_success(api.cancel_vendor_booking(booking["id"], PLANNER))
    validate_error(
        api.cancel_vendor_booking(booking["id"], PLANNER),
        ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE.value,
    )
