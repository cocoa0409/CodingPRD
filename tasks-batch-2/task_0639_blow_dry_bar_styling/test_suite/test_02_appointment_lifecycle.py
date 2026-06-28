"""Appointment lifecycle / settlement parallel state machine and invalid transitions.

Queue A (Difficulty): non_linear_state_machine/nls_appointment_parallel_lifecycle_settlement.
Queue B (Corner): section `state_machines` (appointment-axis instances).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_base_scenario, book_standalone_appointment, check_in, start_service,
    setup_completed_standalone, drive_to_completed,
    make_stylist_headers, TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Queue A: parallel lifecycle x settlement axes ────────────────────────────

def test_complete_advances_lifecycle_only_settlement_stays_unsettled(api):
    """PRD §3.7: "Completion makes the appointment eligible for settlement, but the
    `settlement_status` remains `UNSETTLED` until a settle action runs."

    Design: Difficulty/non_linear_state_machine/nls_appointment_parallel_lifecycle_settlement
    """
    scenario = setup_base_scenario()
    appt = book_standalone_appointment(scenario)
    sty_id = scenario["stylist"]["id"]
    check_in(appt["id"], "ON_TIME")
    start_service(appt["id"], sty_id)
    res = api.complete_appointment(appt["id"], make_stylist_headers(sty_id))
    completed = validate_success(res, 200)
    assert completed["lifecycle_status"] == "COMPLETED"
    assert completed["settlement_status"] == "UNSETTLED"


def test_settle_flips_only_settlement_axis_lifecycle_stays_completed(api):
    """PRD §3.10: "Settlement runs along the appointment's second, independent state axis.
    The `settlement_status` axis runs `UNSETTLED → SETTLED`, with `VOIDED` reached only by
    the no-show and cancel paths described above."
    PRD §3.10: "Settlement advances `settlement_status` to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/nls_appointment_parallel_lifecycle_settlement
    """
    scenario, appt = setup_completed_standalone()
    res = api.settle_appointment(appt["id"], {"tip_cents": 0}, FM)
    settled = validate_success(res, 200)
    assert settled["lifecycle_status"] == "COMPLETED"
    assert settled["settlement_status"] == "SETTLED"


# ─── Queue B: invalid transitions / preconditions / initial state ─────────────

def test_start_from_booked_returns_not_checked_in(api):
    """PRD §3.7: "Starting service is a `Stylist` action that advances
    `CHECKED_IN → IN_SERVICE`. It requires the appointment to be `CHECKED_IN` (otherwise
    `ERR_APPOINTMENT_NOT_CHECKED_IN`, 409) ..."

    Design: Corner/state_machines/sm_start_from_booked_returns_not_checked_in
    """
    scenario = setup_base_scenario()
    appt = book_standalone_appointment(scenario)
    res = api.start_appointment(appt["id"], make_stylist_headers(scenario["stylist"]["id"]))
    validate_error(res, "ERR_APPOINTMENT_NOT_CHECKED_IN", expected_status=409)


def test_cancel_already_cancelled_returns_not_cancellable(api):
    """PRD §3.9: "Cancellation requires the appointment to be in `BOOKED` or `CHECKED_IN`
    (otherwise `ERR_APPOINTMENT_NOT_CANCELLABLE`, 409) ..."

    Design: Corner/state_machines/sm_cancel_already_cancelled_returns_not_cancellable
    """
    scenario = setup_base_scenario()
    appt = book_standalone_appointment(scenario)
    validate_success(api.cancel_appointment(appt["id"], FD), 200)
    res = api.cancel_appointment(appt["id"], FD)
    validate_error(res, "ERR_APPOINTMENT_NOT_CANCELLABLE", expected_status=409)


def test_settle_before_completed_returns_not_completed(api):
    """PRD §3.10: "Settlement requires, across the two axes, that the appointment's
    `lifecycle_status` is `COMPLETED` (otherwise `ERR_APPOINTMENT_NOT_COMPLETED`, 409) ..."

    Design: Corner/state_machines/sm_settle_before_completed_returns_not_completed
    """
    scenario = setup_base_scenario()
    appt = book_standalone_appointment(scenario)
    sty_id = scenario["stylist"]["id"]
    check_in(appt["id"], "ON_TIME")
    start_service(appt["id"], sty_id)  # now IN_SERVICE, not COMPLETED
    res = api.settle_appointment(appt["id"], {"tip_cents": 0}, FM)
    validate_error(res, "ERR_APPOINTMENT_NOT_COMPLETED", expected_status=409)


def test_no_show_before_start_returns_too_early(api):
    """PRD §3.8: "only once the logical clock has reached the appointment's start, meaning
    the clock's `current_minute` is at or after the appointment's `start_minute`; calling
    it before then is rejected with `ERR_NO_SHOW_TOO_EARLY` (409)."

    Design: Corner/state_machines/sm_no_show_before_start_returns_too_early
    """
    # Clock left at startup default 2026-01-01T00:00:00Z -> current_minute 0 < 600.
    scenario = setup_base_scenario()
    appt = book_standalone_appointment(scenario, start_minute=600)
    res = api.no_show_appointment(appt["id"], FD)
    validate_error(res, "ERR_NO_SHOW_TOO_EARLY", expected_status=409)


def test_reinstate_active_member_returns_not_suspended(api):
    """PRD §3.8: "A `FrontDesk` operator reinstates a suspended member, advancing
    `SUSPENDED → ACTIVE`; this requires the member to currently be `SUSPENDED` (otherwise
    `ERR_MEMBER_NOT_SUSPENDED`, 409) ..."

    Design: Corner/state_machines/sm_reinstate_active_member_returns_not_suspended
    """
    from test_helpers import create_member
    member = create_member(full_name="Active")
    res = api.reinstate_member(
        member["id"], {"expected_member_version": member["version"]}, FD)
    validate_error(res, "ERR_MEMBER_NOT_SUSPENDED", expected_status=409)


def test_appointment_initial_states_and_schedule(api):
    """PRD §3.4: "A new appointment is born with `lifecycle_status` of `BOOKED` and
    `settlement_status` of `UNSETTLED`."
    PRD §3.4: "The `scheduled_duration_minutes` equals the style service's
    `base_duration_minutes` plus the sum of `extra_duration_minutes` over every attached
    add-on, and the `end_minute` equals `start_minute` plus `scheduled_duration_minutes`."

    Design: Corner/state_machines/sm_appointment_initial_states
    """
    scenario = setup_base_scenario(service_overrides={"base_duration_minutes": 45})
    res = api.create_appointment(
        {"member_id": scenario["member"]["id"], "chair_id": scenario["chair"]["id"],
         "stylist_id": scenario["stylist"]["id"],
         "style_service_id": scenario["service"]["id"],
         "start_minute": 600, "payment_method": "CREDIT"},
        FD)
    appt = validate_success(res, 201)
    assert appt["lifecycle_status"] == "BOOKED"
    assert appt["settlement_status"] == "UNSETTLED"
    assert appt["scheduled_duration_minutes"] == 45
    assert appt["end_minute"] == 645
