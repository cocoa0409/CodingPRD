"""Provisional vs finalized assignment cost; overtime straddle; guardrail tiering.

Covers Difficulty queue rules: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, set_clock, setup_location, setup_worker,
    setup_pay_period, create_posted_shift, assign_worker,
)


M = make_manager_headers()


def _five_day_week(api, loc_id, worker_id):
    """Post five 10h shifts Mon..Fri and assign the worker to each in order.
    Returns the list of assignment ids in Mon..Fri order."""
    asg_ids = []
    for day in range(1, 6):  # 2026-06-01 .. 2026-06-05
        shift = create_posted_shift(
            api, loc_id,
            start_utc=f"2026-06-0{day}T09:00:00Z",
            end_utc=f"2026-06-0{day}T19:00:00Z",
            headcount_required=1,
        )
        asg = assign_worker(api, loc_id, shift["id"], worker_id)
        asg_ids.append((asg["id"], shift["id"]))
    return asg_ids


def test_provisional_estimate_projects_full_overtime_on_friday(api):
    """PRD §3.8: "For the provisional estimate, the baseline is the worker's
    already-scheduled pay-week hours: the sum of duration_hours over the worker's
    other assignments in the same pay-period that are in SCHEDULED or CONFIRMED
    (excluding this assignment, and excluding any in NO_SHOW, CANCELLED, or
    COMPLETED, and any in other pay-periods)."
    PRD §3.8: "the regular hours are the overtime threshold minus the prior-week
    hours, clamped to lie between zero and the shift's hours, and the overtime
    hours are whatever of the shift's hours remain above that."

    With Mon..Thu (40 scheduled prior hours) the Friday 10h shift is entirely
    overtime: 10h * 2000 * 1.5 = 30000.

    Design: Difficulty/dual_variant_calc/provisional_vs_finalized_cost_diverge_on_noshow
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    asgs = _five_day_week(api, loc["id"], worker["id"])
    fri_id = asgs[4][0]
    data = get_success_data(api.get_assignment(fri_id, M))
    assert data["provisional_cost_cents"] == 30000, (
        f"Friday provisional should be all-OT 30000, got {data['provisional_cost_cents']}")


def test_finalized_cost_drops_overtime_after_monday_noshow(api):
    """PRD §3.8: "Because no-showed and cancelled assignments never complete, they
    contribute zero realized hours — so a worker who no-showed an earlier shift may
    fall below the overtime threshold and finalize cheaper than the provisional
    estimate had assumed."
    PRD §3.4: "every SCHEDULED or CONFIRMED assignment on the shift is advanced to
    COMPLETED, each one stamping its finalized_cost_cents (computed as in §3.8) and
    reconciling its pay-period."

    Same Friday assignment: provisional 30000 (40h prior projected) but finalized
    20000 (Monday no-show drops 10h, leaving 30 realized prior hours, so Friday's
    10h are all regular: 10 * 2000 = 20000).

    Design: Difficulty/dual_variant_calc/provisional_vs_finalized_cost_diverge_on_noshow
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    asgs = _five_day_week(api, loc["id"], worker["id"])
    mon_id = asgs[0][0]
    fri_id, fri_shift = asgs[4]
    # Monday no-show (clock after Monday start).
    set_clock(api, "2026-06-01T09:00:01Z")
    get_success_data(api.no_show_assignment(loc["id"], mon_id, M))
    # Complete Tue..Fri (clock past Friday end).
    set_clock(api, "2026-06-05T19:00:01Z")
    for _, shift_id in asgs[1:]:
        get_success_data(api.complete_shift(loc["id"], shift_id, M))
    data = get_success_data(api.get_assignment(fri_id, M))
    assert data["status"] == "COMPLETED"
    assert data["provisional_cost_cents"] == 30000, (
        f"provisional unchanged at 30000, got {data['provisional_cost_cents']}")
    assert data["finalized_cost_cents"] == 20000, (
        f"finalized should drop to 20000 after Monday no-show, got {data['finalized_cost_cents']}")


def test_provisional_straddles_overtime_boundary(api):
    """PRD §3.8: "the regular hours are the overtime threshold minus the prior-week
    hours, clamped to lie between zero and the shift's hours, and the overtime hours
    are whatever of the shift's hours remain above that."

    Prior week = 36h scheduled; an 8h shift straddles the 40h threshold: 4h regular
    + 4h overtime -> 4*2000 + 4*2000*1.5 = 8000 + 12000 = 20000, rounded once.

    Design: Difficulty/combinatorial_formula/ot_straddle_clamp_three_inputs_mode_a
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    # 36h prior shift earlier in the pay-week.
    s36 = create_posted_shift(api, loc["id"], start_utc="2026-06-01T06:00:00Z",
                              end_utc="2026-06-02T18:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s36["id"], worker["id"])
    s8 = create_posted_shift(api, loc["id"], start_utc="2026-06-03T09:00:00Z",
                             end_utc="2026-06-03T17:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s8["id"], worker["id"])
    assert asg["provisional_cost_cents"] == 20000, (
        f"straddle 4 reg + 4 ot should be 20000, got {asg['provisional_cost_cents']}")


def test_provisional_all_regular_below_overtime_threshold(api):
    """PRD §3.8: "the regular hours are the overtime threshold minus the prior-week
    hours, clamped to lie between zero and the shift's hours, and the overtime hours
    are whatever of the shift's hours remain above that."

    Boundary partner of the straddle case: with no prior hours an 8h shift sits
    entirely below the 40h threshold, so all 8 hours are regular: 8*2000 = 16000,
    zero overtime.

    Design: Difficulty/combinatorial_formula/ot_straddle_clamp_three_inputs_mode_a
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s8 = create_posted_shift(api, loc["id"], start_utc="2026-06-03T09:00:00Z",
                             end_utc="2026-06-03T17:00:00Z", headcount_required=1)
    asg = assign_worker(api, loc["id"], s8["id"], worker["id"])
    assert asg["provisional_cost_cents"] == 16000, (
        f"8h all-regular should be 16000, got {asg['provisional_cost_cents']}")


def test_guardrail_rejects_second_assignment_pushing_projected_over_cap(api):
    """PRD §3.10: "If the projected total computed with the new assignment included
    would be strictly greater than the location's overtime_cost_guardrail_cents, the
    assignment is refused with ERR_OVERTIME_GUARDRAIL_EXCEEDED."
    PRD §3.10: "A pay-period's projected cost is the sum of provisional_cost_cents
    over its assignments in SCHEDULED or CONFIRMED, plus the sum of amount_cents over
    every predictability-ledger entry in that pay-period."

    First 8h assignment costs 16000; the second 8h assignment would also cost 16000
    (prior=8h, still below 40h threshold), projecting 32000 > 20000 guardrail.

    Design: Difficulty/combinatorial_formula/guardrail_depends_on_tiered_provisional_mode_c
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_cost_guardrail_cents=20000,
                         overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sa = create_posted_shift(api, loc["id"], start_utc="2026-06-01T09:00:00Z",
                             end_utc="2026-06-01T17:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sa["id"], worker["id"])
    sb = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                             end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": sb["id"], "worker_id": worker["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_OVERTIME_GUARDRAIL_EXCEEDED.value)


def test_guardrail_allows_projected_total_exactly_at_cap(api):
    """PRD §3.10: "If the projected total computed with the new assignment included
    would be strictly greater than the location's overtime_cost_guardrail_cents, the
    assignment is refused with ERR_OVERTIME_GUARDRAIL_EXCEEDED."

    Boundary partner: with the guardrail set exactly to the projected total of two
    8h assignments (32000), the second assignment lands on (not strictly above) the
    cap and is allowed.

    Design: Difficulty/combinatorial_formula/guardrail_depends_on_tiered_provisional_mode_c
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, overtime_cost_guardrail_cents=32000,
                         overtime_weekly_threshold_hours=40, overtime_multiplier=1.5,
                         predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    sa = create_posted_shift(api, loc["id"], start_utc="2026-06-01T09:00:00Z",
                             end_utc="2026-06-01T17:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], sa["id"], worker["id"])
    sb = create_posted_shift(api, loc["id"], start_utc="2026-06-02T09:00:00Z",
                             end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": sb["id"], "worker_id": worker["id"]}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["provisional_cost_cents"] == 16000
