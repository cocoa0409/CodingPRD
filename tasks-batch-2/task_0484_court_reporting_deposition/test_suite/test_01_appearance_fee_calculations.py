"""Appearance-fee calculations: estimate (scheduled times) vs frozen actual,
the two-hour floor, ceil-to-whole-hour, and the realtime-reporter surcharge.

The actual fee is frozen onto each completed assignment at adjournment (PRD §3.6);
the estimate is a pure read using the scheduled window (PRD §3.6).
"""
from test_helpers import (
    validate_success,
    setup_confirmed_reporter_job,
    setup_insession_realtime_job,
    run_session,
    set_clock,
    adjourn_job,
    make_billing_clerk_headers,
)

BILLING = make_billing_clerk_headers()


def test_appearance_estimate_uses_scheduled_window(api):
    """PRD §3.6: "The estimate differs in exactly one respect: it uses the
    **scheduled** window — the span between `scheduled_end` and `scheduled_start`
    — in place of the actual session times, while applying the identical two-hour
    minimum, round-up-to-whole-hour, and twenty-percent real-time-reporter
    surcharge rules." A reporter-only job scheduled 09:00..12:00 (3h) @10000
    estimates 3*10000=30000.

    Design: Difficulty/dual_variant_calc/appearance_fee_estimate_vs_actual_on_assignment
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T12:00:00Z",
        hourly_appearance_cents=10000)
    data = validate_success(api.get_appearance_estimate(sc.job_id, BILLING))
    assert data["estimated_total_cents"] == 30000, (
        f"3h scheduled @10000 estimate should be 30000, got {data['estimated_total_cents']}")


def test_appearance_actual_uses_actual_session_window(api):
    """PRD §3.6: "The appearance fee a resource earns on a job is computed from the
    **actual** session duration once the job adjourns." PRD §3.6: "The resulting
    `appearance_fee_cents` is frozen onto each completed assignment at adjournment
    and is the authoritative billed value." A job scheduled 3h but adjourned after
    90 minutes bills ceil(90/60)=2h @10000=20000.

    Design: Difficulty/dual_variant_calc/appearance_fee_estimate_vs_actual_on_assignment
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-06-01T09:00:00Z",
        scheduled_end="2026-06-01T12:00:00Z",
        hourly_appearance_cents=10000)
    run_session(sc.job_id, "2026-06-01T09:00:00Z", "2026-06-01T10:30:00Z")
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["appearance_fee_cents"] == 20000, (
        f"90-min actual @10000 should freeze to 20000, got {asg['appearance_fee_cents']}")
    assert asg["status"] == "COMPLETED", (
        f"assignment should be COMPLETED after adjourn, got {asg['status']}")


def test_appearance_fee_realtime_surcharge_with_two_hour_floor(api):
    """PRD §3.6: "There is one surcharge: when the assignment's role is `REPORTER`
    and the job requires real-time, the base is increased by twenty percent — the
    base multiplied by 1.20, with that product rounded half up to the nearest
    cent." PRD §3.6: "take the elapsed time in whole minutes, divide by sixty, and
    round that quotient up to the next whole hour for any partial hour, then take
    whichever is larger of that figure and a two-hour minimum." A 30-min realtime
    reporter session @15000: max(2,1)=2h, base 30000, *1.20=36000.

    Design: Difficulty/combinatorial_formula/appearance_fee_nonlinear_min_ceil_surcharge_mode_a
    """
    sc = setup_insession_realtime_job(
        hourly_appearance_cents=15000,
        scheduled_start="2026-06-04T09:00:00Z",
        scheduled_end="2026-06-04T13:00:00Z",
        session_start="2026-06-04T09:00:00Z")
    set_clock("2026-06-04T09:30:00Z")
    adjourn_job(sc.job_id)
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["appearance_fee_cents"] == 36000, (
        f"realtime reporter 2h floor @15000 *1.20 should be 36000, got "
        f"{asg['appearance_fee_cents']}")


def test_appearance_fee_two_hour_minimum_floor_non_realtime(api):
    """PRD §3.6: "every appearance is billed in whole hours with a floor of two
    hours, and any partial hour is rounded up." A 30-minute actual session for a
    non-realtime reporter @12000 bills max(2,1)=2h => 24000.

    Design: Corner/calculations/appearance_fee_two_hour_minimum_floor
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-07-15T09:00:00Z",
        scheduled_end="2026-07-15T13:00:00Z",
        hourly_appearance_cents=12000)
    run_session(sc.job_id, "2026-07-15T09:00:00Z", "2026-07-15T09:30:00Z")
    asg = validate_success(api.get_assignment(sc.assignment_id, BILLING))
    assert asg["appearance_fee_cents"] == 24000, (
        f"30-min session @12000 with 2h floor should be 24000, got "
        f"{asg['appearance_fee_cents']}")


def test_appearance_estimate_read_uses_scheduled_times_corner(api):
    """PRD §3.6: "The appearance-estimate read returns an `estimated_total_cents`
    integer alongside per-resource `lines`, summing the estimated fees across the
    job's current assignments." A CONFIRMED reporter-only job scheduled 3h @10000
    returns estimated_total_cents==30000.

    Design: Corner/calculations/appearance_estimate_uses_scheduled_times
    """
    sc = setup_confirmed_reporter_job(
        scheduled_start="2026-07-13T09:00:00Z",
        scheduled_end="2026-07-13T12:00:00Z",
        hourly_appearance_cents=10000)
    data = validate_success(api.get_appearance_estimate(sc.job_id, BILLING))
    assert data["estimated_total_cents"] == 30000, (
        f"scheduled 3h @10000 estimate should be 30000, got {data['estimated_total_cents']}")
