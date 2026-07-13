"""Terminal appointments, the re-appointment loop, slot capacity, and demurrage
(estimate vs actual, rounding order, and the last-free-day day boundary).

Covers Difficulty rules: non_linear_state_machine, resource_temporal_overlap,
dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    mk_terminal, mk_booking, mk_chassis, mk_chassis_assigned_booking,
    create_appointment_payload,
    setup_pickup_ready, setup_dispatched_pickup,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# --- non_linear_state_machine: booking re-appointment cycle ---------------

def _setup_chassis_assigned_for_reappointment(api):
    set_clock_terminal = mk_terminal(api, name="Pier E", code="PIERE")
    chassis = mk_chassis(api, chassis_number="CHX5")
    assigned = mk_chassis_assigned_booking(
        api, set_clock_terminal["id"], chassis["id"],
        container_number="MSCU5", last_free_day="2026-05-20T00:00:00Z")
    return set_clock_terminal, assigned


def test_pickup_appointment_cancel_reverts_booking_to_chassis_assigned(api):
    """PRD §3.4: "Canceling the current pickup appointment reverts the booking from
    `APPOINTED` back to `CHASSIS_ASSIGNED`, forming a re-appointment loop."
    PRD §3.4: "On cancellation the appointment moves from `BOOKED` to `CANCELED`,
    the booking's `scheduled_pickup_at` is cleared, and the booking's `version`
    increments; the previously locked `demurrage_estimate_cents` is retained as the
    original projection."

    Design: Difficulty/non_linear_state_machine/booking_reappointment_cycle
    """
    api.set_clock("2026-05-06T00:00:00Z", DISPATCHER)
    terminal, booking = _setup_chassis_assigned_for_reappointment(api)
    appt1 = get_success_data(api.create_appointment(
        create_appointment_payload(booking["id"], terminal["id"], "PICKUP",
                                   "2026-05-13T08:00:00Z", "2026-05-13T12:00:00Z"), DISPATCHER))
    get_success_data(api.cancel_appointment(appt1["id"], DISPATCHER))
    appt = validate_success(api.get_appointment(appt1["id"], DISPATCHER))
    assert appt["status"] == "CANCELED"
    after = validate_success(api.get_booking(booking["id"], DISPATCHER))
    assert after["status"] == "CHASSIS_ASSIGNED"


def test_second_pickup_appointment_returns_booking_to_appointed(api):
    """PRD §3.4: "When a pickup appointment is booked for a booking that is
    currently `CHASSIS_ASSIGNED`, the booking advances to `APPOINTED`."

    Design: Difficulty/non_linear_state_machine/booking_reappointment_cycle
    """
    api.set_clock("2026-05-06T00:00:00Z", DISPATCHER)
    terminal, booking = _setup_chassis_assigned_for_reappointment(api)
    appt1 = get_success_data(api.create_appointment(
        create_appointment_payload(booking["id"], terminal["id"], "PICKUP",
                                   "2026-05-13T08:00:00Z", "2026-05-13T12:00:00Z"), DISPATCHER))
    get_success_data(api.cancel_appointment(appt1["id"], DISPATCHER))
    appt2 = get_success_data(api.create_appointment(
        create_appointment_payload(booking["id"], terminal["id"], "PICKUP",
                                   "2026-05-14T08:00:00Z", "2026-05-14T12:00:00Z"), DISPATCHER))
    assert appt2["status"] == "BOOKED"
    after = validate_success(api.get_booking(booking["id"], DISPATCHER))
    assert after["status"] == "APPOINTED"


# --- resource_temporal_overlap: terminal slot capacity (half-open) --------

def test_overlapping_appointment_rejected_when_slot_full(api):
    """PRD §3.4: "The system counts the `BOOKED` appointments at that terminal
    whose half-open window intersects the requested half-open window; if that count
    is already at or above the terminal's `slot_capacity_per_window`, the request is
    rejected with `ERR_APPOINTMENT_SLOT_FULL`."

    Design: Difficulty/resource_temporal_overlap/terminal_appointment_slot_capacity_half_open
    """
    terminal = mk_terminal(api, name="Pier O", code="PIERO", slot_capacity_per_window=1)
    bkg1 = mk_booking(api, terminal["id"], container_number="MSCUI")
    bkg2 = mk_booking(api, terminal["id"], container_number="MSCUJ")
    get_success_data(api.create_appointment(
        create_appointment_payload(bkg1["id"], terminal["id"], "PICKUP",
                                   "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), DISPATCHER))
    resp = api.create_appointment(
        create_appointment_payload(bkg2["id"], terminal["id"], "PICKUP",
                                   "2026-05-10T10:00:00Z", "2026-05-10T14:00:00Z"), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_SLOT_FULL, expected_status=409)


def test_adjacent_appointment_allowed_half_open(api):
    """PRD §3.4: "Because the intervals are half-open, two windows that merely touch
    at an endpoint — one ending exactly where the next begins — do not intersect and
    do not compete for the same slot."

    Design: Difficulty/resource_temporal_overlap/terminal_appointment_slot_capacity_half_open
    """
    terminal = mk_terminal(api, name="Pier O", code="PIERO", slot_capacity_per_window=1)
    bkg1 = mk_booking(api, terminal["id"], container_number="MSCUI")
    bkg2 = mk_booking(api, terminal["id"], container_number="MSCUJ")
    get_success_data(api.create_appointment(
        create_appointment_payload(bkg1["id"], terminal["id"], "PICKUP",
                                   "2026-05-10T08:00:00Z", "2026-05-10T12:00:00Z"), DISPATCHER))
    # Adjacent window [12:00, 16:00) touches the first only at 12:00 -> no collision.
    appt3 = get_success_data(api.create_appointment(
        create_appointment_payload(bkg2["id"], terminal["id"], "PICKUP",
                                   "2026-05-10T12:00:00Z", "2026-05-10T16:00:00Z"), DISPATCHER))
    assert appt3["status"] == "BOOKED"


# --- dual_variant_calc: demurrage estimate vs actual ----------------------

_EST_KW = dict(
    clock="2026-05-06T00:00:00Z", demurrage_daily_rate_cents=12500,
    last_free_day="2026-05-10T00:00:00Z", linehaul_base_cents=45000,
    container_number="MSCU1", appt_start="2026-05-13T08:00:00Z",
    appt_end="2026-05-15T23:59:59Z", leg_start="2026-05-15T09:00:00Z",
    leg_end="2026-05-15T12:00:00Z",
)


def test_demurrage_estimate_locked_at_pickup_appointment(api):
    """PRD §3.4: "take the origin terminal's `demurrage_daily_rate_cents`, multiply
    it by one plus the port fee percentage of 0.075 (that is, by 1.075), and round
    that per-day charge half-up to whole cents."
    PRD §3.4: "Multiply the already-rounded per-day charge by that integer day count
    to get `demurrage_estimate_cents`."

    Design: Difficulty/dual_variant_calc/demurrage_estimate_vs_actual_on_booking
    """
    ctx = setup_pickup_ready(api, **_EST_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    # scheduled_pickup_at = 2026-05-13; LFD = 2026-05-10 -> 3 days; 13438 * 3.
    assert booking["demurrage_estimate_cents"] == 40314


def test_demurrage_actual_at_dispatch_differs_from_estimate(api):
    """PRD §3.6: "The actual demurrage uses the identical formula and pinned rounding
    order as the estimate — the terminal's `demurrage_daily_rate_cents` times 1.075,
    rounded half-up to a whole-cent per-day charge, multiplied by the whole UTC
    calendar days strictly after `last_free_day` — but its basis is `actual_pickup_at`
    (the logical clock at dispatch) rather than `scheduled_pickup_at`."

    Design: Difficulty/dual_variant_calc/demurrage_estimate_vs_actual_on_booking
    """
    ctx = setup_dispatched_pickup(api, dispatch_clock="2026-05-15T10:00:00Z", **_EST_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    # actual_pickup_at = 2026-05-15; LFD = 2026-05-10 -> 5 days; 13438 * 5.
    assert booking["demurrage_actual_cents"] == 67190
    assert booking["demurrage_estimate_cents"] == 40314
    assert booking["demurrage_actual_cents"] != booking["demurrage_estimate_cents"]


# --- combinatorial_formula: round-per-day-then-sum ------------------------

_MODE_B_KW = dict(
    clock="2026-05-06T00:00:00Z", demurrage_daily_rate_cents=12500,
    last_free_day="2026-05-10T00:00:00Z", container_number="MSCU4",
    appt_start="2026-05-06T08:00:00Z", appt_end="2026-05-14T23:59:59Z",
    leg_start="2026-05-13T09:00:00Z", leg_end="2026-05-13T12:00:00Z",
)


def test_demurrage_actual_rounds_per_day_before_summing(api):
    """PRD §2.5: "The specific rounding points are called out with each formula in
    §3 — most notably, the demurrage per-day charge is rounded before it is
    multiplied by the day count, and the invoice's volume discount and fuel
    surcharge are each rounded independently."

    Design: Difficulty/combinatorial_formula/demurrage_round_per_day_then_sum_mode_b
    """
    ctx = setup_dispatched_pickup(api, dispatch_clock="2026-05-13T10:00:00Z", **_MODE_B_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    # round_half_up(12500 * 1.075) = 13438; times 3 days = 40314.
    assert booking["demurrage_actual_cents"] == 40314


def test_demurrage_rounding_order_yields_40314_not_40313(api):
    """PRD §3.6: "The actual demurrage uses the identical formula and pinned rounding
    order as the estimate — the terminal's `demurrage_daily_rate_cents` times 1.075,
    rounded half-up to a whole-cent per-day charge, multiplied by the whole UTC
    calendar days strictly after `last_free_day`..."

    Design: Difficulty/combinatorial_formula/demurrage_round_per_day_then_sum_mode_b
    """
    ctx = setup_dispatched_pickup(api, dispatch_clock="2026-05-13T10:00:00Z", **_MODE_B_KW)
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    # Sum-then-round would give round(13437.5 * 3) = 40313; the pinned order gives 40314.
    assert booking["demurrage_actual_cents"] == 40314
    assert booking["demurrage_actual_cents"] != 40313


# --- boundary_precision_check: demurrage day boundary at/after LFD ---------

def test_demurrage_zero_when_pickup_dispatched_on_last_free_day(api):
    """PRD §2.5: "Demurrage counts each calendar date strictly after the container's
    last free day; per-diem counts the calendar dates a chassis has been out, less
    its free-day allowance."
    PRD §2.5: "Both day counts are floored at zero — a basis on or before the
    reference date yields zero days, never a negative amount."

    Design: Difficulty/boundary_precision_check/demurrage_day_boundary_at_and_after_lfd
    """
    ctx = setup_dispatched_pickup(
        api, dispatch_clock="2026-05-10T09:00:00Z", clock="2026-05-06T00:00:00Z",
        demurrage_daily_rate_cents=12500, last_free_day="2026-05-10T00:00:00Z",
        container_number="MSCUC", appt_start="2026-05-10T06:00:00Z",
        appt_end="2026-05-12T23:59:59Z", leg_start="2026-05-10T08:00:00Z",
        leg_end="2026-05-10T10:00:00Z",
    )
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    assert booking["demurrage_actual_cents"] == 0


def test_demurrage_one_day_when_pickup_one_day_after_last_free_day(api):
    """PRD §2.5: "Demurrage counts each calendar date strictly after the container's
    last free day; per-diem counts the calendar dates a chassis has been out, less
    its free-day allowance."
    PRD §3.6: "the terminal's `demurrage_daily_rate_cents` times 1.075, rounded
    half-up to a whole-cent per-day charge, multiplied by the whole UTC calendar days
    strictly after `last_free_day`".

    Design: Difficulty/boundary_precision_check/demurrage_day_boundary_at_and_after_lfd
    """
    ctx = setup_dispatched_pickup(
        api, dispatch_clock="2026-05-11T09:00:00Z", clock="2026-05-06T00:00:00Z",
        demurrage_daily_rate_cents=12500, last_free_day="2026-05-10T00:00:00Z",
        container_number="MSCUD", appt_start="2026-05-11T06:00:00Z",
        appt_end="2026-05-12T23:59:59Z", leg_start="2026-05-11T08:00:00Z",
        leg_end="2026-05-11T10:00:00Z",
    )
    booking = validate_success(api.get_booking(ctx["booking_id"], DISPATCHER))
    # one calendar day after LFD -> 13438 * 1.
    assert booking["demurrage_actual_cents"] == 13438
