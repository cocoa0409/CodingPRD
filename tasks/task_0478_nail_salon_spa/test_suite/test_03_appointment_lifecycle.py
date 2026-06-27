"""Appointment booking/payment state machines: initial state, invalid and
terminal transitions, station occupancy side effect, deposit idempotency, and
the two parallel (booking x payment) dimensions evolving independently."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    setup_base, make_station, make_menu_item, make_technician, make_client,
    book_appointment, attach_add_on, confirm, check_in, start_service,
    checkout, drive_to_in_service, inject_client_state, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def test_appointment_initial_status_is_requested_unpaid(api):
    """PRD §3.5: "A new appointment begins with `booking_status` of `REQUESTED`
    and `payment_status` of `UNPAID`, the initial states of the two parallel
    dimensions described in Section 3.6."

    Design: Corner/state_machines/appointment_initial_status_is_requested_unpaid
    """
    set_clock("2026-07-03T12:00:00Z")
    base = setup_base()
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"], origin="WALK_IN")
    assert appt["booking_status"] == "REQUESTED"
    assert appt["payment_status"] == "UNPAID"


def test_confirm_from_completed_returns_invalid_state(api):
    """PRD §3.6: "An attempt to drive either dimension along a transition that is
    not defined from its current value is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_completed_returns_invalid_state
    """
    set_clock("2026-07-04T12:00:00Z")
    base = setup_base()
    completed = None
    started = drive_to_in_service(base["client"]["id"], base["technician"]["id"],
                                  base["station"]["id"], base["menu"]["id"],
                                  origin="WALK_IN")
    completed = checkout(started["id"], started["version"])
    assert completed["booking_status"] == "COMPLETED"

    res = api.confirm_appointment(completed["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancelled_appointment_is_terminal_for_booking(api):
    """PRD §3.6: "The **booking dimension**, `booking_status`, runs `REQUESTED` ->
    `CONFIRMED` -> `CHECKED_IN` -> `IN_SERVICE` -> `COMPLETED`, with `CANCELLED`
    and `NO_SHOW` as alternative terminal outcomes; `COMPLETED`, `CANCELLED`, and
    `NO_SHOW` are all terminal."
    PRD §3.6: "An attempt to drive either dimension along a transition that is not
    defined from its current value is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancelled_appointment_is_terminal_for_booking
    """
    set_clock("2026-07-05T12:00:00Z")
    base = setup_base()
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"],
                            origin="APPOINTMENT", start_at="2026-07-05T15:00:00Z")
    confirm(appt["id"])
    cancelled = validate_success(api.cancel_appointment(appt["id"], FRONT_DESK))
    assert cancelled["booking_status"] == "CANCELLED"

    res = api.cancel_appointment(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_STATE")


def test_start_service_occupies_station_side_effect(api):
    """PRD §3.9: "Starting service sets that station's `in_service_appointment_id`
    to this appointment's `id`, marking the chair occupied, and increments the
    appointment's `version` by one."

    Design: Corner/state_machines/start_service_occupies_station_side_effect
    """
    set_clock("2026-07-06T12:00:00Z")
    base = setup_base()
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"], origin="WALK_IN")
    confirm(appt["id"])
    check_in(appt["id"])
    start_service(appt["id"], base["technician"]["id"])

    station = validate_success(api.get_station(base["station"]["id"], FRONT_DESK))
    assert station["in_service_appointment_id"] == appt["id"]


def test_idempotent_pay_deposit_second_call_rejected(api):
    """PRD §3.6: "A `FrontDesk` operator or `SalonManager` pays the owed deposit
    on an appointment whose `payment_status` is `UNPAID`".
    PRD §3.6: "An attempt to drive either dimension along a transition that is not
    defined from its current value is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/idempotent_pay_deposit_second_call_rejected
    """
    set_clock("2026-07-08T12:00:00Z")
    base = setup_base()
    inject_client_state(base["client"]["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-07-07T00:00:00Z")
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"],
                            origin="APPOINTMENT", start_at="2026-07-08T13:00:00Z")
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))

    res = api.pay_deposit(appt["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Difficulty: parallel booking x payment dimensions
# ---------------------------------------------------------------------------
def test_deposit_held_while_booking_still_requested(api):
    """PRD §3.6: "Because the dimensions are independent, a still-`REQUESTED`
    appointment can hold a deposit before it is ever confirmed."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_booking_and_payment_dimensions
    """
    set_clock("2026-03-10T00:00:00Z")
    base = setup_base(base_price_cents=3000, duration_minutes=30)
    inject_client_state(base["client"]["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-03-09T00:00:00Z")
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"],
                            origin="APPOINTMENT", start_at="2026-03-10T13:00:00Z")
    assert appt["deposit_due_cents"] == 2000

    after_pay = validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    assert after_pay["payment_status"] == "DEPOSIT_HELD"
    assert after_pay["booking_status"] == "REQUESTED"


def test_confirm_advances_booking_independent_of_held_deposit(api):
    """PRD §3.6: "The two dimensions interact at specific moments — a deposit-
    required client cannot confirm until a deposit is held, checkout settles
    payment while completing the booking, a no-show may forfeit a held deposit —
    but otherwise each advances on its own."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_booking_and_payment_dimensions
    """
    set_clock("2026-03-10T00:00:00Z")
    base = setup_base(base_price_cents=3000, duration_minutes=30)
    inject_client_state(base["client"]["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-03-09T00:00:00Z")
    appt = book_appointment(base["client"]["id"], base["technician"]["id"],
                            base["station"]["id"], base["menu"]["id"],
                            origin="APPOINTMENT", start_at="2026-03-10T13:00:00Z")
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))

    confirmed = validate_success(api.confirm_appointment(appt["id"], FRONT_DESK))
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_HELD"
