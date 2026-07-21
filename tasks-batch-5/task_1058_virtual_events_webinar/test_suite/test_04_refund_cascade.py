"""Refunding a registration: the money/seat unwind, the availability flip and
the waitlist promotion that follow from it."""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    assert_collected_money_conservation,
    add_registration,
    pay_registration,
    read_registration,
    read_event,
    read_ticket_type,
    setup_published_event,
)

ORG = TEST_USERS["organizer_headers"]


def _summit_h_seat_sold_out_with_waitlist():
    """Summit H: quota 1, registration A holds and has paid for the only seat,
    registration B sits on the waitlist behind it."""
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit H", "capacity": 50},
        ticket_overrides={"quota": 1},
    )
    reg_a = add_registration(event["id"], ticket_type["id"], "a@example.com")
    pay_registration(reg_a["id"], 20600)
    reg_b = add_registration(
        event["id"], ticket_type["id"], "b@example.com", waitlist_if_full=True
    )
    return event, ticket_type, reg_a, reg_b


def test_refund_unwinds_money_and_releases_the_seat(api):
    """PRD 3.5: "The **first link** unwinds the money and the seat together: the
    event's `gross_collected_cents` is reduced by the registration's
    `amount_paid_cents`, then `amount_paid_cents` is set to zero, and the
    registration's `attendance_status` transitions to `WITHDRAWN`, which in turn
    decrements the ticket type's `sold_count` by one and the event's
    `registered_count` by one."

    Design: Difficulty/transitive_cascade/refund_chains_seat_release_to_availability_flip_to_waitlist_promotion
    """
    event, ticket_type, reg_a, reg_b = _summit_h_seat_sold_out_with_waitlist()
    assert reg_b["attendance_status"] == "WAITLISTED", (
        "Setup must leave registration B on the waitlist"
    )

    refunded = validate_success(
        api.refund_registration(reg_a["id"], "attendee cancelled", ORG), 200
    )
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["attendance_status"] == "WITHDRAWN", (
        f"The refund must withdraw the row, got {refunded['attendance_status']}"
    )
    assert refunded["amount_paid_cents"] == 0
    assert read_event(event["id"])["gross_collected_cents"] == 0


def test_refund_flips_availability_then_promotes_the_earliest_waitlisted_row(api):
    """PRD 3.5: "The **second link** follows from that seat release: because
    `sold_count` has now fallen below `quota`, the availability recomputation
    flips the ticket type's `availability_status` from `SOLD_OUT` back to
    `AVAILABLE`."
    PRD 3.5: "The **third link** follows from the availability flip: the
    waitlisted registration on that same ticket type with the earliest
    `created_at` is promoted from `WAITLISTED` to `REGISTERED`, its
    `amount_due_cents` is written by the provisional pricing run evaluated at the
    current logical clock, and the ticket type's `sold_count` and the event's
    `registered_count` are each incremented back by one."

    Design: Difficulty/transitive_cascade/refund_chains_seat_release_to_availability_flip_to_waitlist_promotion
    """
    event, ticket_type, reg_a, reg_b = _summit_h_seat_sold_out_with_waitlist()

    validate_success(
        api.refund_registration(reg_a["id"], "attendee cancelled", ORG), 200
    )

    promoted = read_registration(reg_b["id"])
    assert promoted["attendance_status"] == "REGISTERED", (
        f"The waitlisted row must be promoted, got {promoted['attendance_status']}"
    )
    assert promoted["amount_due_cents"] == 20600, (
        "Promotion prices the row with the provisional run; expected 20600, got "
        f"{promoted['amount_due_cents']}"
    )

    tt = read_ticket_type(ticket_type["id"])
    assert tt["sold_count"] == 1, (
        f"The promoted row takes the released seat back, expected 1, got "
        f"{tt['sold_count']}"
    )
    assert tt["availability_status"] == "SOLD_OUT", (
        "With the promoted row holding the only seat the type is SOLD_OUT again"
    )
    assert read_event(event["id"])["registered_count"] == 1


def _summit_r_paid_registration():
    event, ticket_type = setup_published_event(
        event_overrides={"name": "Summit R", "capacity": 50},
        ticket_overrides={"quota": 5},
    )
    registration = add_registration(event["id"], ticket_type["id"], "money@example.com")
    registration = pay_registration(registration["id"], 20600)
    return event, ticket_type, registration


def test_refund_returns_collected_money_to_its_pre_payment_value(api):
    """PRD 2.11: "Taking payment is the forward action and issuing a refund is
    the compensating action; after a payment followed by a refund,
    `gross_collected_cents` returns to exactly its pre-payment value and the
    registration's `amount_paid_cents` is zero, leaving no drift."

    Design: Difficulty/compensating_invariant/refund_restores_collected_money_with_zero_drift
    """
    event, ticket_type, registration = _summit_r_paid_registration()
    assert read_event(event["id"])["gross_collected_cents"] == 20600, (
        "Setup must leave 20600 cents collected before the compensating action"
    )

    refunded = validate_success(
        api.refund_registration(registration["id"], "duplicate purchase", ORG), 200
    )
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["amount_paid_cents"] == 0, (
        f"Expected amount_paid_cents back to 0, got {refunded['amount_paid_cents']}"
    )
    assert read_event(event["id"])["gross_collected_cents"] == 0, (
        "gross_collected_cents must return to exactly its pre-payment value of 0"
    )


def test_refund_leaves_the_money_invariant_holding_across_the_event(api):
    """PRD 2.11: "An event's `gross_collected_cents` is always equal to the sum
    of `amount_paid_cents` across the event's registrations whose
    `payment_status` is `PAID`."
    PRD 3.5: "The **first link** unwinds the money and the seat together: the
    event's `gross_collected_cents` is reduced by the registration's
    `amount_paid_cents`, then `amount_paid_cents` is set to zero, and the
    registration's `attendance_status` transitions to `WITHDRAWN`, which in turn
    decrements the ticket type's `sold_count` by one and the event's
    `registered_count` by one."

    Design: Difficulty/compensating_invariant/refund_restores_collected_money_with_zero_drift
    """
    event, ticket_type, registration = _summit_r_paid_registration()
    validate_success(
        api.refund_registration(registration["id"], "duplicate purchase", ORG), 200
    )

    refreshed_event = read_event(event["id"])
    rows, _ = validate_paginated(
        api.list_registrations(ORG, params={"event_id": event["id"]})
    )
    assert_collected_money_conservation(refreshed_event, rows)
    assert read_registration(registration["id"])["attendance_status"] == "WITHDRAWN"
    assert read_ticket_type(ticket_type["id"])["sold_count"] == 0
