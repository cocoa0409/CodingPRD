"""Seasonal rollup: coverage variants, per-pass revenue rounding, incident tallies."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_scheduled_shift, clock_in, clock_out, set_clock,
    setup_lot, new_parking_pass,
    new_beach, new_zone, new_lifeguard, new_incident,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]


def _setup_early_clockout_beach(api):
    beach, zone, tower, guard, shift = setup_scheduled_shift(
        api, scheduled_start="2026-07-15T09:00:00Z", scheduled_end="2026-07-15T17:00:00Z",
        clock="2026-07-15T09:00:00Z",
    )
    clock_in(api, shift["id"], guard["id"])
    set_clock(api, "2026-07-15T13:00:00Z")
    clock_out(api, shift["id"], guard["id"])
    return beach, zone, tower, guard, shift


def test_scheduled_coverage_counts_planned_length(api):
    """PRD §3.8: "`scheduled_coverage_minutes` sums, over every shift that is not `CANCELLED`,
    the planned length `scheduled_end` minus `scheduled_start` expressed in whole minutes,
    counting planned schedule length regardless of whether the guard actually clocked in."

    Design: Difficulty/dual_variant_calc/staffing_scheduled_vs_actual_coverage
    """
    beach, *_ = _setup_early_clockout_beach(api)
    report = validate_success(api.get_seasonal_report(beach["id"], CAPTAIN), 200)
    assert report["scheduled_coverage_minutes"] == 480, (
        f"09:00-17:00 planned = 480 min, got {report['scheduled_coverage_minutes']}"
    )


def test_actual_coverage_counts_clocked_duration(api):
    """PRD §3.8: "`actual_coverage_minutes` sums, over every shift whose `clock_in_at` is set,
    the real clocked duration from `clock_in_at` to `clock_out_at` — or to the current
    logical-clock instant when the guard has not yet clocked out — again in whole minutes; a
    guard who clocked out early thus contributes fewer minutes than scheduled."

    Design: Difficulty/dual_variant_calc/staffing_scheduled_vs_actual_coverage
    """
    beach, *_ = _setup_early_clockout_beach(api)
    report = validate_success(api.get_seasonal_report(beach["id"], CAPTAIN), 200)
    assert report["actual_coverage_minutes"] == 240, (
        f"09:00-13:00 clocked = 240 min, got {report['actual_coverage_minutes']}"
    )


def _setup_two_weekday_passes(api):
    beach, lot = setup_lot(api, total_spaces=50, daily_rate_cents=100, clock="2026-07-15T10:00:00Z")
    new_parking_pass(api, lot["id"], plate="P1", vehicle_type="CAR", pass_type="DAILY", is_resident=False)
    new_parking_pass(api, lot["id"], plate="P2", vehicle_type="CAR", pass_type="DAILY", is_resident=False)
    return beach, lot


def test_seasonal_revenue_rounds_per_pass_then_sums(api):
    """PRD §3.8: "for each pass, its `fee_cents` is first grossed up by the town surcharge of
    8.5 percent — multiplying by 1.085 and rounding that line half-up to whole cents — and only
    then are the per-pass lines summed; the surcharge is applied and rounded per pass before
    summation, never after."

    Design: Difficulty/combinatorial_formula/seasonal_revenue_round_per_pass_then_sum
    """
    beach, lot = _setup_two_weekday_passes(api)
    report = validate_success(api.get_seasonal_report(beach["id"], CAPTAIN), 200)
    assert report["total_parking_revenue_cents"] == 218, (
        f"round(100*1.085)=109 per pass, 109+109=218, got {report['total_parking_revenue_cents']}"
    )


def test_seasonal_revenue_rounds_per_pass_not_after_sum(api):
    """PRD §3.8: "the surcharge is applied and rounded per pass before summation, never after."

    Design: Difficulty/combinatorial_formula/seasonal_revenue_round_per_pass_then_sum
    """
    beach, lot = _setup_two_weekday_passes(api)
    report = validate_success(api.get_seasonal_report(beach["id"], CAPTAIN), 200)
    total = report["total_parking_revenue_cents"]
    assert total == 218, f"per-pass rounding must give 218, got {total}"
    assert total != 217, "sum-then-round (round(200*1.085)=217) is forbidden; must round per pass"


def test_seasonal_report_incident_tallies(api):
    """PRD §3.8: "`total_incidents` counts all incidents in the beach's zones, `rescue_count`
    counts those of type `RESCUE`, and `ems_escalations` counts those that reached
    `ESCALATED_EMS`."

    Design: Corner/endpoints/corner_seasonal_report_incident_counts
    """
    beach = new_beach(api)
    zone = new_zone(api, beach["id"], min_guards_required=1)
    guard = new_lifeguard(api, beach["id"])
    new_incident(api, zone["id"], guard["id"], incident_type="RESCUE", occurred_at="2026-07-15T10:00:00Z")
    new_incident(api, zone["id"], guard["id"], incident_type="MEDICAL", occurred_at="2026-07-15T11:00:00Z")
    report = validate_success(api.get_seasonal_report(beach["id"], CAPTAIN), 200)
    assert report["total_incidents"] == 2, f"expected 2 incidents, got {report['total_incidents']}"
    assert report["rescue_count"] == 1, f"expected 1 rescue, got {report['rescue_count']}"
    assert report["ems_escalations"] == 0, f"expected 0 escalations, got {report['ems_escalations']}"
