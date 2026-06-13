"""Invalid transitions, terminal-state lockdown, guarded transitions, idempotency, and
the shuttle-cancel cross-entity detach.

Queue B (Corner) instances from the state_machines section.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_booked_reservation, create_checked_in_reservation,
    create_shuttle_trip, assign_reservation_to_trip, set_clock,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


def test_checkout_from_booked_without_checkin_invalid_state():
    """PRD §3.6: "A `LotOperator` (or `FacilityAdmin`) closes out a reservation by
    checking it out, which is permitted only when the reservation is currently
    `CHECKED_IN`; a check-out from any other occupancy state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/checkout_from_booked_without_checkin_returns_invalid_state
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lis", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    res = api_client.check_out_reservation(reservation["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_from_cancelled_terminal_lockdown():
    """PRD §3.8: "Cancellation is permitted only while the reservation is `BOOKED` and
    the current clock is still strictly before `scheduled_start`; a cancel from any
    other occupancy state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Ltl", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    res = api_client.cancel_reservation(reservation["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_gate_exit_on_in_out_disallowed_lot_rejected():
    """PRD §3.5: "A temporary exit is permitted only from `CHECKED_IN`, and only when
    the lot allows it; a temporary exit attempt on a lot whose `in_out_allowed` is false
    is rejected with `ERR_IN_OUT_NOT_ALLOWED`."

    Design: Corner/state_machines/gate_exit_on_in_out_disallowed_lot_returns_error
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lio", "kind": "SURFACE_LOT", "standard_capacity": 5,
                       "in_out_allowed": False},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    res = api_client.gate_exit_reservation(checked_in["id"], OPERATOR)
    validate_error(res, "ERR_IN_OUT_NOT_ALLOWED", expected_status=409)


def test_depart_from_scheduled_without_boarding_invalid_state():
    """PRD §3.9: "Any trip transition requested from a state where it is not defined
    (opening boarding on a non-`SCHEDULED` trip, departing a non-`BOARDING` trip,
    cancelling a non-`SCHEDULED` trip) is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/depart_from_scheduled_without_boarding_invalid_state
    """
    set_clock("2026-07-01T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "Lsd", "kind": "SURFACE_LOT", "standard_capacity": 2,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    trip = create_shuttle_trip(lot["id"], depart_at="2026-07-01T10:00:00Z", seat_capacity=4)
    res = api_client.depart_shuttle_trip(trip["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_check_in_twice_second_rejected():
    """PRD §3.5: "Check-in is permitted only when the reservation is currently
    `BOOKED`".
    PRD §3.5: "Any gate transition requested from a state in which it is not defined —
    a check-in on something not `BOOKED` ... — is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/check_in_twice_idempotency_second_rejected
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lci", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    res = api_client.check_in_reservation(checked_in["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_shuttle_cancel_detaches_riders_and_zeros_seats():
    """PRD §3.9: "from `SCHEDULED` the operator may cancel the trip, moving `status`
    from `SCHEDULED` to the terminal `CANCELLED`; cancellation detaches every rider,
    clearing each assigned reservation's `shuttle_trip_id` and driving `seats_taken` to
    0."

    Design: Corner/state_machines/shuttle_cancel_detaches_riders_and_zeros_seats
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lsc", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-02T10:00:00Z", scheduled_end="2026-07-03T10:00:00Z")
    trip = create_shuttle_trip(scenario["lot"]["id"], depart_at="2026-07-01T12:00:00Z",
                               seat_capacity=4)
    assign_reservation_to_trip(reservation["id"], trip["id"])

    cancelled = validate_success(api_client.cancel_shuttle_trip(trip["id"], OPERATOR), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_taken"] == 0

    res_after = get_success_data(api_client.get_reservation(reservation["id"], ADMIN))
    assert res_after["shuttle_trip_id"] is None
