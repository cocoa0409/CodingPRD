"""Compensating invariants: customer money conserved across a weather cancel
(REFUND + FORFEIT == PAYMENT) and handler scheduled minutes conserved across
assign + cancel-release (PRD §3.3, §3.7).
"""
from test_helpers import (
    validate_success,
    sum_of_type,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Difficulty/compensating_invariant/weather_cancel_money_conservation
# =====================================================================
def _setup_weather_held_sheep_with_permit(api):
    """CONFIRMED sheep booking (quoted 17270, deposit 5181 paid) with one
    ISSUED ANIMAL_EXHIBITION permit, placed on WEATHER_HOLD at
    2026-06-16T10:00:00Z via a fresh MANDATORY_HOLD assessment."""
    ctx = fx.setup_confirmed_sheep_booking(
        venue_overrides={
            "name": "County Fairground", "address": "4 Fair Rd",
            "distance_miles": 15, "max_guest_capacity": 300,
            "requires_animal_permit": True,
        },
        with_permit=True,
    )
    fx.set_clock("2026-06-16T10:00:00Z")
    wa = fx.create_assessment(ctx["booking"]["id"], "2026-06-16T09:30:00Z")
    validate_success(api.weather_hold(ctx["booking"]["id"], wa["id"], fx.COORD))
    return ctx


def test_weather_cancel_refund_conserves_every_paid_cent(api):
    """PRD §3.7: "A weather cancellation refunds everything paid minus 2500
    cents for each of the booking's permits in `SUBMITTED` or `ISSUED` status
    — non-recoverable filing fees — floored at zero."
    PRD §3.7: "In all variants the unrefunded remainder, when nonzero, is
    appended as a `FORFEIT` entry, and refunds are appended as `REFUND`
    entries."

    Design: Difficulty/compensating_invariant/weather_cancel_money_conservation
    """
    ctx = _setup_weather_held_sheep_with_permit(api)
    validate_success(api.cancel_booking(ctx["booking"]["id"], "WEATHER", fx.COORD))

    ledger = fx.list_ledger(ctx["booking"]["id"])
    paid = sum_of_type(ledger, "PAYMENT")
    refunded = sum_of_type(ledger, "REFUND")
    forfeited = sum_of_type(ledger, "FORFEIT")
    assert paid == 5181
    assert refunded == 2681   # 5181 - 2500 for the one ISSUED permit
    assert forfeited == 2500  # the non-recoverable filing fee
    # Conserved quantity: every paid cent is either refunded or forfeited.
    assert paid == refunded + forfeited


def test_weather_cancel_marks_booking_and_payment_status(api):
    """PRD §3.7: "A `Coordinator` cancels with `reason` `WEATHER` from
    `CONFIRMED` or `WEATHER_HOLD`, or with `reason` `COMPLIANCE` from
    `CONFIRMED`."
    PRD §3.7: "Otherwise `payment_status` becomes `REFUND_FULL` when the
    refund equals the amount paid, `REFUND_PARTIAL` when the refund is
    positive but smaller, and `FORFEITED` when nothing is refunded."

    Design: Difficulty/compensating_invariant/weather_cancel_money_conservation
    """
    ctx = _setup_weather_held_sheep_with_permit(api)
    cancelled = validate_success(
        api.cancel_booking(ctx["booking"]["id"], "WEATHER", fx.COORD))
    assert cancelled["status"] == "CANCELLED_WEATHER", cancelled["status"]
    # Refund 2681 is positive but smaller than the 5181 paid.
    assert cancelled["payment_status"] == "REFUND_PARTIAL"


# =====================================================================
# Difficulty/compensating_invariant/assign_release_handler_minutes_conservation
# =====================================================================
def _setup_draft_booking_with_assigned_handler():
    """DRAFT 120-minute booking (2026-06-20 10:00-12:00) with handler Hank
    ASSIGNED; Hank's scheduled_minutes_total is 120."""
    ctx = fx.setup_draft_booking(
        start_time="2026-06-20T10:00:00Z", end_time="2026-06-20T12:00:00Z",
        guest_count=10,
    )
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    assignment = fx.assign_handler(ctx["booking"]["id"], handler["id"], "LEAD")
    ctx["handler"] = handler
    ctx["assignment"] = assignment
    return ctx


def test_assign_adds_event_minutes_to_handler_total(api):
    """PRD §3.3: "Assigning a handler to a booking is a coordinator action
    that takes a `handler_id` and a `role` of `LEAD` or `ASSISTANT` and
    creates the assignment in `ASSIGNED` status, incrementing the handler's
    `scheduled_minutes_total` by the booking's event duration."
    PRD §3.3: "The total starts at 0 and is recomputed on every assign, every
    release, and every completion cascade"

    Design: Difficulty/compensating_invariant/assign_release_handler_minutes_conservation
    """
    ctx = fx.setup_draft_booking(
        start_time="2026-06-20T10:00:00Z", end_time="2026-06-20T12:00:00Z",
        guest_count=10,
    )
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 0

    fx.assign_handler(ctx["booking"]["id"], handler["id"], "LEAD")
    # The forward action adds the 120-minute event.
    assert fx.get_handler(handler["id"])["scheduled_minutes_total"] == 120


def test_cancel_release_returns_handler_minutes_to_zero(api):
    """PRD §3.7: "Every `ASSIGNED` staff assignment moves to `RELEASED` with
    `release_reason` `BOOKING_CANCELLED`, and each release recomputes the
    affected handler's `scheduled_minutes_total`."
    PRD §3.7: "When the booking was never paid (`total_paid_cents` is zero),
    no ledger entries are created for any variant and `payment_status` stays
    `UNPAID`."

    Design: Difficulty/compensating_invariant/assign_release_handler_minutes_conservation
    """
    ctx = _setup_draft_booking_with_assigned_handler()
    booking_id = ctx["booking"]["id"]

    cancelled = validate_success(api.cancel_booking(
        booking_id, "CUSTOMER", make_customer_headers(ctx["customer"]["id"])))
    assert cancelled["status"] == "CANCELLED_CUSTOMER", cancelled["status"]

    # The compensating release restores the pre-assignment total — no drift.
    assert fx.get_handler(ctx["handler"]["id"])["scheduled_minutes_total"] == 0

    sa = [a for a in fx.list_staff_assignments(booking_id)
          if a["id"] == ctx["assignment"]["id"]][0]
    assert sa["status"] == "RELEASED", sa["status"]
    assert sa["release_reason"] == "BOOKING_CANCELLED", sa["release_reason"]
    # Never paid: the refund waterfall creates no ledger entries at all.
    assert fx.list_ledger(booking_id) == []
