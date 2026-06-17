"""Reservation occupancy/billing lifecycle: transitions, parallel dimensions,
invalid-state and terminal-lockdown rejections, and the seat-retire precondition.

Translates queue-A difficulty rule `non_linear_state_machine`
(reservation_parallel_occupancy_and_billing_dimensions) and queue-B Corner
`state_machines` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_employee_headers,
    create_reservation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty A: non_linear_state_machine — parallel occupancy + billing
# ---------------------------------------------------------------------------
def test_parallel_dimensions_checkin_then_amenity(api):
    """PRD §3.7: "A reservation carries two independent status dimensions. The
    occupancy_status dimension tracks the booking lifecycle through BOOKED,
    CHECKED_IN, COMPLETED, NO_SHOW_RELEASED, and CANCELLED, of which the last
    three are terminal. The billing_status dimension, covered in Section 3.5 and
    3.8, tracks chargeback through NONE, PROVISIONAL, FINALIZED, and VOID, and
    evolves on its own schedule. The two are deliberately decoupled."
    PRD §3.5: "Adding the first line to a reservation whose billing_status is
    NONE advances that reservation to billing_status PROVISIONAL".

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_and_billing_dimensions
    """
    env, resv = fx.setup_checked_in_reservation(
        booking_date="2026-06-25", start_minute=540, end_minute=1080,
        checkin_minute=545, level=6)
    emp_id = env["employee"]["id"]
    # occupancy is CHECKED_IN; adding the first amenity advances billing only
    fx.add_amenity_line(resv["id"], emp_id, "MONITOR", 1000, 1)
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert data["occupancy_status"] == "CHECKED_IN"
    assert data["billing_status"] == "PROVISIONAL"


def test_parallel_dimensions_billing_advances_without_changing_occupancy(api):
    """PRD §3.7: "A reservation carries two independent status dimensions. ...
    The billing_status dimension, covered in Section 3.5 and 3.8, tracks
    chargeback through NONE, PROVISIONAL, FINALIZED, and VOID, and evolves on its
    own schedule. The two are deliberately decoupled."
    PRD §3.4: "A new reservation enters occupancy_status BOOKED and
    billing_status NONE."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_occupancy_and_billing_dimensions
    """
    env = fx.setup_floor_plan(level=26, clock_date="2026-06-25", clock_minute=500)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-06-25", 540, 1080)
    assert resv["occupancy_status"] == "BOOKED"
    assert resv["billing_status"] == "NONE"
    # add an amenity while still BOOKED: billing advances, occupancy unchanged
    fx.add_amenity_line(resv["id"], emp_id, "PARKING", 500, 1)
    data = get_success_data(api.get_reservation(resv["id"], make_employee_headers(emp_id)))
    assert data["occupancy_status"] == "BOOKED"
    assert data["billing_status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Corner: state_machines invalid-transition / terminal-lockdown
# ---------------------------------------------------------------------------
def test_checkin_from_already_checked_in_returns_invalid_state(api):
    """PRD §3.7: "A check-in attempt from the wrong occupancy state is rejected
    with ERR_INVALID_STATE".

    Design: Corner/state_machines/checkin_from_already_checked_in_returns_invalid_state
    """
    env, resv = fx.setup_checked_in_reservation(
        booking_date="2026-08-03", start_minute=540, end_minute=600,
        checkin_minute=545, level=7)
    emp_id = env["employee"]["id"]
    resp = api.checkin_reservation(resv["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_terminal_cancelled_reservation_rejects_checkin(api):
    """PRD §3.7: "A transition attempted from an occupancy state that does not
    permit it is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_cancelled_reservation_rejects_checkin
    """
    env = fx.setup_floor_plan(level=8, clock_date="2026-08-05", clock_minute=500)
    emp_id = env["employee"]["id"]
    resv = fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-08-05", 600, 660)
    get_success_data(api.cancel_reservation(resv["id"], make_employee_headers(emp_id)))
    resp = api.checkin_reservation(resv["id"], make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_seat_retire_blocked_when_active_reservation_exists(api):
    """PRD §3.2: "From AVAILABLE, a seat may also be RETIRED, but only when no
    reservation on that seat is currently in the BOOKED or CHECKED_IN state ...
    Attempting a transition from a state that does not permit it — for example
    taking an already OUT_OF_SERVICE seat out of service, or retiring a seat with
    live bookings — is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/seat_retire_blocked_when_active_reservation_exists
    """
    env = fx.setup_floor_plan(level=10, clock_date="2026-08-07", clock_minute=500)
    emp_id = env["employee"]["id"]
    fx.create_seat_reservation(emp_id, env["seat"]["id"], "2026-08-07", 600, 660)
    resp = api.seat_retire(env["seat"]["id"], FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
