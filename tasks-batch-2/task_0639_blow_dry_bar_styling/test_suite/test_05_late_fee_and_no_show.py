"""Late-fee threshold at check-in, no-show strike accrual, suspension cascade, and the
cross-entity dependency of check-in on member status.

Queue A (Difficulty): boundary_precision_check/bpc_late_fee_grace_boundary;
                      cross_entity_state_dependency/ces_checkin_depends_on_member_status.
Queue B (Corner): section `calculations` (late-fee grace / cap);
                  section `cross_cutting_complexity_layers` (no-show suspension cascade).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_base_scenario, book_standalone_appointment, set_clock,
    setup_member_with_no_show_strikes, TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]


# ─── Queue A: late-fee grace boundary (10 free, 11 charged) ───────────────────

def test_late_fee_at_11_minutes_charges_100(api):
    """PRD §3.7: "The grace allowance is ten minutes: arriving ten minutes late or fewer
    incurs no fee, while eleven minutes late or more does."
    PRD §3.7: "the fee is one dollar (100 cents) for each minute beyond the ten-minute
    grace — that is, the billable minutes are `late_minutes` minus ten ..."

    late_minutes 11 -> billable 1 -> fee 100 -> service_charge 6000 + 100 = 6100.

    Design: Difficulty/boundary_precision_check/bpc_late_fee_grace_boundary
    """
    scenario = setup_base_scenario(service_overrides={"base_price_cents": 6000})
    appt = book_standalone_appointment(scenario)
    res = api.check_in_appointment(
        appt["id"], {"arrival_status": "LATE", "late_minutes": 11}, FD)
    checked_in = validate_success(res, 200)
    assert checked_in["service_charge_cents"] == 6100


def test_late_fee_at_grace_boundary_10_minutes_is_free(api):
    """PRD §3.7: "The grace allowance is ten minutes: arriving ten minutes late or fewer
    incurs no fee, while eleven minutes late or more does."

    late_minutes 10 (== grace) -> fee 0 -> service_charge stays 6000.

    Design: Difficulty/boundary_precision_check/bpc_late_fee_grace_boundary
    """
    scenario = setup_base_scenario(service_overrides={"base_price_cents": 6000})
    appt = book_standalone_appointment(scenario)
    res = api.check_in_appointment(
        appt["id"], {"arrival_status": "LATE", "late_minutes": 10}, FD)
    checked_in = validate_success(res, 200)
    assert checked_in["service_charge_cents"] == 6000
    assert checked_in["lifecycle_status"] == "CHECKED_IN"


def test_late_fee_within_grace_10_minutes_is_zero(api):
    """PRD §3.7: "The grace allowance is ten minutes: arriving ten minutes late or fewer
    incurs no fee, while eleven minutes late or more does."
    PRD §3.7: "When the arrival is `LATE` and the recorded `late_minutes` exceeds the grace
    allowance, a late fee is computed and added to the appointment's `service_charge_cents`."

    A LATE check-in at exactly 10 minutes (== grace) adds no fee; the charge stays 6000 and
    lifecycle becomes CHECKED_IN.

    Design: Corner/calculations/calc_late_fee_within_grace_is_zero
    """
    scenario = setup_base_scenario(service_overrides={"base_price_cents": 6000})
    appt = book_standalone_appointment(scenario)
    res = api.check_in_appointment(
        appt["id"], {"arrival_status": "LATE", "late_minutes": 10}, FD)
    checked_in = validate_success(res, 200)
    assert checked_in["service_charge_cents"] == 6000
    assert checked_in["lifecycle_status"] == "CHECKED_IN"


def test_late_fee_capped_at_2500(api):
    """PRD §3.7: "capped at twenty-five dollars (2,500 cents); the fee added is the lesser
    of the per-minute charge and that cap."

    late_minutes 40 -> billable 30 -> 30*100 = 3000 capped to 2500 -> 6000 + 2500 = 8500.

    Design: Corner/calculations/calc_late_fee_capped
    """
    scenario = setup_base_scenario(service_overrides={"base_price_cents": 6000})
    appt = book_standalone_appointment(scenario)
    res = api.check_in_appointment(
        appt["id"], {"arrival_status": "LATE", "late_minutes": 40}, FD)
    checked_in = validate_success(res, 200)
    assert checked_in["service_charge_cents"] == 8500


# ─── Queue B: no-show suspension cascade after the third strike ───────────────

def test_third_no_show_suspends_member(api):
    """PRD §3.8: "When this count reaches the suspension threshold of three strikes, the
    member's `status` cascades to `SUSPENDED`: two strikes leave the member `ACTIVE`, and
    the third strike (a count of three or more) suspends them."

    Design: Corner/cross_cutting_complexity_layers/cascade_no_show_suspends_member_after_third_strike
    """
    scenario, member = setup_member_with_no_show_strikes(3)
    assert member["no_show_strikes"] == 3
    assert member["status"] == "SUSPENDED"


def test_two_no_shows_leave_member_active(api):
    """PRD §3.8: "two strikes leave the member `ACTIVE`, and the third strike (a count of
    three or more) suspends them."

    Design: Corner/cross_cutting_complexity_layers/cascade_no_show_suspends_member_after_third_strike
    """
    scenario, member = setup_member_with_no_show_strikes(2)
    assert member["no_show_strikes"] == 2
    assert member["status"] == "ACTIVE"


# ─── Queue A: check-in depends on member status (Appointment -> Member) ───────

def test_checkin_rejected_when_member_suspended(api):
    """PRD §3.7: "Checking in is a `FrontDesk` action that advances `BOOKED → CHECKED_IN`.
    It requires the appointment to be `BOOKED` (otherwise `ERR_APPOINTMENT_NOT_BOOKED`,
    409) and the subject member to be `ACTIVE` (otherwise `ERR_MEMBER_SUSPENDED`, 409)."
    PRD §3.8: "two strikes leave the member `ACTIVE`, and the third strike (a count of
    three or more) suspends them."

    A member with a BOOKED appointment who is then suspended via 3 no-shows cannot be
    checked in for that appointment: ERR_MEMBER_SUSPENDED (409).

    The target appointment is booked while the member is still ACTIVE; the three strike
    appointments are booked and no-showed afterward (a suspended member could not be the
    subject of a fresh booking per §3.4, so the target must pre-exist).

    Design: Difficulty/cross_entity_state_dependency/ces_checkin_depends_on_member_status
    """
    scenario = setup_base_scenario()
    set_clock("2026-01-01T11:00:00Z")
    member_id = scenario["member"]["id"]
    # Target appointment booked while ACTIVE (later non-overlapping slot).
    target = book_standalone_appointment(scenario, start_minute=700)
    # Accrue 3 strikes on separate appointments at 600 (each no-show releases the chair).
    for _ in range(3):
        ns = book_standalone_appointment(scenario, start_minute=600)
        validate_success(api.no_show_appointment(ns["id"], FD), 200)

    member = validate_success(api.get_member(member_id, FD), 200)
    assert member["status"] == "SUSPENDED"
    assert member["no_show_strikes"] == 3

    res = api.check_in_appointment(target["id"], {"arrival_status": "ON_TIME"}, FD)
    validate_error(res, "ERR_MEMBER_SUSPENDED", expected_status=409)


def test_checkin_allowed_after_member_reinstated(api):
    """PRD §3.7: "Checking in is a `FrontDesk` action that advances `BOOKED → CHECKED_IN`.
    It requires the appointment to be `BOOKED` (otherwise `ERR_APPOINTMENT_NOT_BOOKED`,
    409) and the subject member to be `ACTIVE` (otherwise `ERR_MEMBER_SUSPENDED`, 409)."
    PRD §3.8: "Reinstatement resets `no_show_strikes` to zero, returns `status` to
    `ACTIVE`, and increments the member's `version` by one."

    Reinstating the suspended member flips status back to ACTIVE, after which the same
    BOOKED appointment checks in successfully — the appointment transition tracks the
    member's restored state.

    Design: Difficulty/cross_entity_state_dependency/ces_checkin_depends_on_member_status
    """
    scenario = setup_base_scenario()
    set_clock("2026-01-01T11:00:00Z")
    member_id = scenario["member"]["id"]
    target = book_standalone_appointment(scenario, start_minute=700)
    for _ in range(3):
        ns = book_standalone_appointment(scenario, start_minute=600)
        validate_success(api.no_show_appointment(ns["id"], FD), 200)
    suspended = validate_success(api.get_member(member_id, FD), 200)
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api.reinstate_member(
        member_id, {"expected_member_version": suspended["version"]}, FD), 200)
    assert reinstated["status"] == "ACTIVE"

    checked_in = validate_success(
        api.check_in_appointment(target["id"], {"arrival_status": "ON_TIME"}, FD), 200)
    assert checked_in["lifecycle_status"] == "CHECKED_IN"
