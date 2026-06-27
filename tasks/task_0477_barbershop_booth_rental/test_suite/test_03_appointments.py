"""Booking appointments and the BOOKED fork (PRD §3.4).

Covers the three-way BOOKED fork (check-in / no-show / cancel), the computed
slot end, shift-containment and chair-overlap geometry, and booking-time guards.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_appointment,
    setup_shop_with_barber_chair_shift,
    book_appointment,
    check_in,
    set_clock,
    create_appointment_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_appointment_booked_forks_to_cancelled_and_no_show(api):
    """PRD §3.4: "A successful cancel moves `BOOKED → CANCELLED` with no fee."
    PRD §3.8: "Marking the no-show moves the appointment `BOOKED → NO_SHOW` and
    always adds one to the customer's `no_show_strikes`."

    Design: Difficulty/non_linear_state_machine/appointment_booked_branching_fork
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Fork Shop", "tax_rate_pct": 0,
            "late_grace_minutes": 10, "no_show_fee_cents": 0,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt_cancel = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    appt_noshow = book_appointment(ctx, start_utc="2026-06-10T11:00:00Z")

    cancelled = validate_success(api.cancel_appointment(appt_cancel["id"], RECEPTION), 200)
    assert cancelled["status"] == "CANCELLED", cancelled

    set_clock("2026-06-10T11:30:00Z")
    noshow = validate_success(api.no_show_appointment(appt_noshow["id"], RECEPTION), 200)
    assert noshow["status"] == "NO_SHOW", noshow

    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["no_show_strikes"] == 1, cust


def test_appointment_booked_forks_to_checked_in(api):
    """PRD §3.6: "Check-in moves the appointment `BOOKED → CHECKED_IN`, opens its
    ticket seeded with the appointment's `service_item_id` and `addon_ids`, sets
    the appointment's `ticket_id`".

    Design: Difficulty/non_linear_state_machine/appointment_booked_branching_fork
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Fork Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    checked = validate_success(api.check_in_appointment(appt["id"], RECEPTION), 200)
    assert checked["status"] == "CHECKED_IN", checked
    assert checked["ticket_id"] is not None, checked


def test_appointment_end_utc_computed(api):
    """PRD §3.4: "The slot's `end_utc` is computed, not supplied: it is `start_utc`
    advanced by the service's `duration_minutes` plus the sum of `extra_minutes`
    over every add-on named in `addon_ids`."

    Design: Corner/entities/appointment_end_utc_computed_ignores_client_value
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    addon = get_success_data(api_client.create_addon(
        {"shop_id": ctx["shop"]["id"], "name": "Beard", "price_cents": 1500,
         "extra_minutes": 15}, OWNER))
    appt = book_appointment(ctx, start_utc="2026-06-10T09:15:00Z", addon_ids=[addon["id"]])
    assert_appointment(appt)
    # 09:15 + 30m service + 15m addon = 10:00
    assert appt["end_utc"] == "2026-06-10T10:00:00Z", appt
    assert appt["status"] == "BOOKED"


def test_cancel_after_start_rejected(api):
    """PRD §3.4: "a cancellation at or after the start time is too late and is
    refused with `ERR_CANCEL_TOO_LATE`."

    Design: Corner/state_machines/cancel_appointment_after_start_returns_cancel_too_late
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    set_clock("2026-06-10T10:00:00Z")  # exactly start
    res = api.cancel_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_CANCEL_TOO_LATE")


def test_check_in_twice_rejected(api):
    """PRD §2.8 / §3: re-driving a transition from the wrong state yields
    `ERR_INVALID_STATE` (target resource not in the required state — appointment
    not BOOKED).

    Design: Corner/state_machines/checkin_already_checked_in_returns_invalid_state
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    appt = book_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    check_in(appt["id"])
    res = api.check_in_appointment(appt["id"], RECEPTION)
    validate_error(res, "ERR_INVALID_STATE")


def test_book_outside_shift_window_rejected(api):
    """PRD §3.4: "the slot must lie fully within a single `SCHEDULED` shift of the
    same barber on the same chair ... failing which the booking is rejected with
    `ERR_OUTSIDE_SHIFT`."

    Design: Corner/state_machines/book_outside_shift_window_returns_outside_shift
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    # Shift is 09:00-18:00; booking at 19:00 is outside it.
    res = api.create_appointment(
        create_appointment_payload(
            ctx["shop"]["id"], ctx["customer"]["id"], ctx["barber"]["id"],
            ctx["chair"]["id"], ctx["service"]["id"], "2026-06-10T19:00:00Z"),
        RECEPTION,
    )
    validate_error(res, "ERR_OUTSIDE_SHIFT")


def test_book_with_nonexistent_chair_rejected(api):
    """PRD §2.8: "that every foreign key carried in the body resolves within the
    shop (`ERR_REFERENCED_ENTITY_NOT_FOUND`, 404)".

    Design: Corner/entities/referenced_chair_not_found_on_appointment_create
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    res = api.create_appointment(
        create_appointment_payload(
            ctx["shop"]["id"], ctx["customer"]["id"], ctx["barber"]["id"],
            NON_EXISTENT_UUID, ctx["service"]["id"], "2026-06-10T10:00:00Z"),
        RECEPTION,
    )
    validate_error(res, "ERR_REFERENCED_ENTITY_NOT_FOUND")


def test_get_appointment_nonexistent_returns_not_found(api):
    """PRD §2.8: "rejects on the first identifier that does not resolve, returning
    that identifier's specific not-found error — `ERR_SHOP_NOT_FOUND`,
    `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`, as applicable."

    Design: Corner/errors/get_appointment_nonexistent_returns_appointment_not_found
    """
    res = api.get_appointment(NON_EXISTENT_UUID, OWNER)
    validate_error(res, "ERR_APPOINTMENT_NOT_FOUND")
