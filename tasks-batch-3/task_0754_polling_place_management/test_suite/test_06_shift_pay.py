"""Shift pay: scheduled vs actual variants, tiered overtime, per-shift rounding order.

Queue A (difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
import pytest
from test_helpers import (
    TEST_USERS,
    get_success_data,
    create_election, create_place, deploy_equipment, create_kit_at_place,
    create_certified_worker, create_active_assignment,
    setup_shift_scheduled, worked_shift_gross_pay,
    create_shift_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]


# ---- dual_variant_calc / shift_pay_scheduled_vs_actual_diverge ----

def test_scheduled_projection_pay_at_creation(api):
    """PRD §3.5: "The system computes `scheduled_hours` as the planned window length — the
    seconds between `scheduled_start` and `scheduled_end` divided by 3600, rounded half-up to
    four decimals — and from it computes the provisional gross pay `scheduled_pay_cents` (the
    scheduled-projection pay variant described below)."

    Design: Difficulty/dual_variant_calc/shift_pay_scheduled_vs_actual_diverge
    """
    ctx = setup_shift_scheduled(api, scheduled_start="2026-11-03T06:00:00Z",
                                scheduled_end="2026-11-03T17:00:00Z")
    shift = ctx["shift"]
    assert shift["scheduled_hours"] == pytest.approx(11.0)
    assert shift["scheduled_pay_cents"] == 22813, (
        f"11h base pay = 14600 regular + 8213 overtime = 22813, got {shift['scheduled_pay_cents']}"
    )


def test_actual_final_pay_diverges_from_scheduled(api):
    """PRD §3.5: "On check-out the system stamps `check_out_time` from the logical clock,
    computes `actual_hours` as the seconds between `check_in_time` and `check_out_time`
    divided by 3600 rounded half-up to four decimals, and computes the final gross pay
    `gross_pay_cents` from `actual_hours` (the actual-final pay variant)."

    Design: Difficulty/dual_variant_calc/shift_pay_scheduled_vs_actual_diverge
    """
    ctx = worked_shift_gross_pay(api, scheduled_start="2026-11-03T06:00:00Z",
                                 scheduled_end="2026-11-03T17:00:00Z",
                                 check_in_iso="2026-11-03T06:00:00Z",
                                 check_out_iso="2026-11-03T15:30:00Z")
    shift = ctx["shift"]
    assert shift["actual_hours"] == pytest.approx(9.5)
    assert shift["gross_pay_cents"] == 18706
    assert shift["scheduled_pay_cents"] - shift["gross_pay_cents"] == 4107, (
        "scheduled (22813) minus actual (18706) gross must diverge by 4107"
    )


# ---- combinatorial_formula / shift_pay_nonlinear_tiered_overtime_mode_a ----

def test_lead_overtime_pay_is_nonlinear(api):
    """PRD §3.5: "The applicable hourly rate is 2450 cents when the shift's `is_lead` is true
    and 1825 cents otherwise."
    PRD §3.5: "Regular pay is the regular hours multiplied by the rate, rounded half-up to
    whole cents. Overtime pay is the overtime hours multiplied by the rate multiplied by an
    overtime multiplier of 1.5, rounded half-up to whole cents independently. Gross pay is the
    sum of those two rounded components."

    Design: Difficulty/combinatorial_formula/shift_pay_nonlinear_tiered_overtime_mode_a
    """
    ctx = worked_shift_gross_pay(api, is_lead=True, scheduled_start="2026-11-03T06:00:00Z",
                                 scheduled_end="2026-11-03T16:00:00Z",
                                 check_in_iso="2026-11-03T06:00:00Z",
                                 check_out_iso="2026-11-03T15:30:00Z")
    shift = ctx["shift"]
    assert shift["gross_pay_cents"] == 25113, (
        f"lead 9.5h = 19600 regular + 5513 overtime = 25113, got {shift['gross_pay_cents']}"
    )


def test_lead_shift_uses_actual_hours_and_lead_flag(api):
    """PRD §3.5: "On creation the shift copies `poll_worker_id`, `polling_place_id`, and
    `is_lead` from its parent assignment".
    PRD §3.5: "The applicable hourly rate is 2450 cents when the shift's `is_lead` is true and
    1825 cents otherwise."

    Design: Difficulty/combinatorial_formula/shift_pay_nonlinear_tiered_overtime_mode_a
    """
    ctx = worked_shift_gross_pay(api, is_lead=True, scheduled_start="2026-11-03T06:00:00Z",
                                 scheduled_end="2026-11-03T16:00:00Z",
                                 check_in_iso="2026-11-03T06:00:00Z",
                                 check_out_iso="2026-11-03T15:30:00Z")
    shift = ctx["shift"]
    assert shift["is_lead"] is True
    assert shift["actual_hours"] == pytest.approx(9.5)


# ---- combinatorial_formula / place_payroll_round_per_shift_then_sum_mode_b ----

def _two_half_hour_shifts_checked_out(api):
    """Place (station_capacity=2) with two workers each working a 0.5h shift 06:00-06:30,
    both CHECKED_OUT. Returns (place_id, shift_a, shift_b)."""
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"], min_workers_required=1,
                      staffing_capacity=5, station_capacity=2)
    deploy_equipment(api, place_id=pp["id"])
    create_kit_at_place(api, election_id=el["id"], place_id=pp["id"])
    wa = create_certified_worker(api, full_name="W A", email="a@x.com")
    aa = create_active_assignment(api, worker_id=wa["id"], place_id=pp["id"])
    wb = create_certified_worker(api, full_name="W B", email="b@x.com")
    ab = create_active_assignment(api, worker_id=wb["id"], place_id=pp["id"])
    get_success_data(api.open_place(pp["id"], CAPTAIN))
    sa = get_success_data(api.create_shift(
        create_shift_payload(aa["id"], "2026-11-03T06:00:00Z", "2026-11-03T06:30:00Z"), CAPTAIN))
    sb = get_success_data(api.create_shift(
        create_shift_payload(ab["id"], "2026-11-03T06:00:00Z", "2026-11-03T06:30:00Z"), CAPTAIN))
    get_success_data(api.set_clock("2026-11-03T06:00:00Z", ADMIN))
    get_success_data(api.check_in(sa["id"], CAPTAIN))
    get_success_data(api.check_in(sb["id"], CAPTAIN))
    get_success_data(api.set_clock("2026-11-03T06:30:00Z", ADMIN))
    sa = get_success_data(api.check_out(sa["id"], CAPTAIN))
    sb = get_success_data(api.check_out(sb["id"], CAPTAIN))
    return pp["id"], sa, sb


def test_each_half_hour_shift_rounds_up_independently(api):
    """PRD §2.7: "When pay is computed, the regular-pay component and the overtime-pay
    component are each rounded half-up to whole cents *independently*, and only then summed;
    there is no separate rounding of the sum."

    Design: Difficulty/combinatorial_formula/place_payroll_round_per_shift_then_sum_mode_b
    """
    _, sa, sb = _two_half_hour_shifts_checked_out(api)
    assert sa["gross_pay_cents"] == 913, f"0.5h*1825=912.5 rounds half-up to 913, got {sa['gross_pay_cents']}"
    assert sb["gross_pay_cents"] == 913


def test_place_payroll_sums_rounded_per_shift(api):
    """PRD §2.7: "When a place's total payroll is aggregated across its shifts, each shift's
    already-rounded gross pay is summed as an integer with no further rounding — the per-shift
    rounding is authoritative, and summing raw unrounded amounts and rounding once at the end
    is explicitly forbidden."

    Design: Difficulty/combinatorial_formula/place_payroll_round_per_shift_then_sum_mode_b
    """
    pp_id, _, _ = _two_half_hour_shifts_checked_out(api)
    place = get_success_data(api.get_polling_place(pp_id, ADMIN))
    assert place["total_payroll_cents"] == 1826, (
        f"913 + 913 = 1826 (round-per-shift-then-sum), got {place['total_payroll_cents']}"
    )


# ---- boundary_precision_check / overtime_gt_eight_hours_boundary ----

def test_exactly_eight_hours_has_no_overtime(api):
    """PRD §3.5: "the regular hours are the lesser of H and 8.0, and the overtime hours are H
    minus 8.0 when that difference is positive and zero otherwise — so overtime accrues only
    when H is strictly greater than 8.0."

    Design: Difficulty/boundary_precision_check/overtime_gt_eight_hours_boundary
    """
    ctx = worked_shift_gross_pay(api, scheduled_start="2026-11-03T06:00:00Z",
                                 scheduled_end="2026-11-03T14:00:00Z",
                                 check_in_iso="2026-11-03T06:00:00Z",
                                 check_out_iso="2026-11-03T14:00:00Z")
    shift = ctx["shift"]
    assert shift["actual_hours"] == pytest.approx(8.0)
    assert shift["gross_pay_cents"] == 14600, (
        f"8.0h*1825 = 14600 with zero overtime, got {shift['gross_pay_cents']}"
    )


def test_just_over_eight_hours_accrues_overtime(api):
    """PRD §3.5: "the overtime hours are H minus 8.0 when that difference is positive and zero
    otherwise — so overtime accrues only when H is strictly greater than 8.0."

    Design: Difficulty/boundary_precision_check/overtime_gt_eight_hours_boundary
    """
    ctx = worked_shift_gross_pay(api, scheduled_start="2026-11-03T06:00:00Z",
                                 scheduled_end="2026-11-03T15:00:00Z",
                                 check_in_iso="2026-11-03T06:00:00Z",
                                 check_out_iso="2026-11-03T14:15:00Z")
    shift = ctx["shift"]
    assert shift["actual_hours"] == pytest.approx(8.25)
    assert shift["gross_pay_cents"] == 15284, (
        f"8.25h = 14600 regular + 684 overtime = 15284, got {shift['gross_pay_cents']}"
    )
