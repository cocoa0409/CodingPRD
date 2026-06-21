"""The dual-variant wage stack: daily vs weekly overtime, the half-time/full-extra
premium math, gross reconciliation, exempt zeroing, break premiums, and the
tipped true-up.

Covers Queue A dual_variant_calc, combinatorial_formula (gross), the 8h boundary,
the immediate-consistency claim, and Queue B calculation instances.
"""
from test_helpers import (
    validate_success,
    setup_ca_employer, setup_tx_employer, create_employee as mk_employee,
    create_closed_punch, create_draft_week, submit_week,
    setup_multi_day_worker,
    create_break_record_payload, create_tip_declaration_payload,
    make_employee_headers,
    SUP1,
)


# ─── Dual-variant divergence (Queue A) ────────────────

def test_ca_daily_method_14h_day_yields_ot_240_dt_120(api):
    """PRD §3.6: "the day's straight hours are the lesser of the day's worked hours
    and daily_ot_threshold_hours (default 8); the day's overtime hours are the
    worked hours capped at daily_dt_threshold_hours (default 12) minus the
    eight-hour line, never below zero ... and the day's double-time hours are
    whatever worked hours exceed twelve, never below zero."

    Design: Difficulty/dual_variant_calc/ot_method_diverges_ca_daily_vs_flsa_weekly
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["regular_minutes"] == 480
    assert data["ot_minutes"] == 240
    assert data["dt_minutes"] == 120


def test_flsa_weekly_method_14h_single_day_yields_no_ot(api):
    """PRD §3.6: "at a worksite whose rule set leaves daily overtime disabled (the
    FLSA weekly pattern), the daily totals are zero, so overtime is simply the
    weekly hours beyond forty and double time is zero."

    Design: Difficulty/dual_variant_calc/ot_method_diverges_ca_daily_vs_flsa_weekly
    """
    employer, ruleset, worksite = setup_tx_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    # 14h in the week is below the 40h weekly line → all straight, no OT/DT.
    assert data["regular_minutes"] == 840
    assert data["ot_minutes"] == 0
    assert data["dt_minutes"] == 0


# ─── Exempt vs non-exempt gross divergence (Queue A) ──

def test_nonexempt_14h_ca_gross_36000(api):
    """PRD §3.6: "For a NON_EXEMPT employee, the straight component is base_rate_cents
    times total worked hours, rounded half up to whole cents; the overtime premium is
    the regular rate times 0.5 times the overtime hours ... the double-time premium is
    the regular rate times 1.0 times the double-time hours ... gross_wages_cents is the
    sum of these five independently rounded components."

    Design: Difficulty/dual_variant_calc/gross_diverges_exempt_vs_nonexempt
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    # straight 28000 + ot_premium 4000 + dt_premium 4000 = 36000
    assert data["gross_wages_cents"] == 36000


def test_exempt_14h_ca_gross_zeroed(api):
    """PRD §3.6: "For an EXEMPT employee the entire hourly stack is forced to zero:
    regular_minutes, ot_minutes, dt_minutes, break_premium_hours, tip_true_up_cents,
    and gross_wages_cents are all zero, because salaried hourly pay is out of scope
    and exempt workers accrue no overtime, double time, or break premium."

    Design: Difficulty/dual_variant_calc/gross_diverges_exempt_vs_nonexempt
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["gross_wages_cents"] == 0
    assert data["ot_minutes"] == 0
    assert data["dt_minutes"] == 0


# ─── Combinatorial premium stack (Queue A) ────────────

def test_regular_rate_half_time_premium_stack_nonlinear(api):
    """PRD §3.6: "Because straight time is already paid on every hour worked, the
    overtime premium is the half-time uplift — a multiplier of 0.5 on the regular
    rate — and the double-time premium is the full extra — a multiplier of 1.0 —
    layered on top of straight time."

    Design: Difficulty/combinatorial_formula/regular_rate_half_time_premium_nonlinear
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["regular_minutes"] == 480
    assert data["ot_minutes"] == 240
    assert data["dt_minutes"] == 120
    assert data["gross_wages_cents"] == 36000


def test_ot_premium_valued_at_half_the_regular_rate(api):
    """PRD §3.6: "the overtime premium is the regular rate times 0.5 times the
    overtime hours (ot_minutes divided by sixty), rounded half up".

    A 9h CA day at base 2000: 8h regular + 1h OT, no DT. The OT premium is the
    half-time uplift (2000 * 0.5 * 1) = 1000 on top of straight pay (2000 * 9 =
    18000), giving gross 19000 — distinct from instance 1's 14h/DT case.

    Design: Difficulty/combinatorial_formula/regular_rate_half_time_premium_nonlinear
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T17:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T17:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["regular_minutes"] == 480
    assert data["ot_minutes"] == 60
    assert data["dt_minutes"] == 0
    # straight 18000 + ot_premium 1000 = 19000
    assert data["gross_wages_cents"] == 19000


# ─── 8h daily boundary (Queue A boundary_precision_check) ──

def test_exactly_8h_day_has_no_daily_ot(api):
    """PRD §3.6: "the day's straight hours are the lesser of the day's worked hours
    and daily_ot_threshold_hours (default 8); the day's overtime hours are the
    worked hours capped at daily_dt_threshold_hours (default 12) minus the
    eight-hour line, never below zero".

    Design: Difficulty/boundary_precision_check/daily_ot_threshold_exactly_8h_no_ot
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["regular_minutes"] == 480
    assert data["ot_minutes"] == 0
    # straight 16000, no premiums.
    assert data["gross_wages_cents"] == 16000


def test_just_over_8h_day_accrues_daily_ot(api):
    """PRD §3.6: "the day's overtime hours are the worked hours capped at
    daily_dt_threshold_hours (default 12) minus the eight-hour line, never below
    zero — that is, the band between eight and twelve hours".

    Just past the strict eight-hour line: an 8h45m day yields 45 minutes of daily
    OT, confirming the boundary is exclusive of exactly 8h (the X+1 side of the
    daily_ot_threshold_exactly_8h instance's X point).

    Design: Difficulty/boundary_precision_check/daily_ot_threshold_exactly_8h_no_ot
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T16:45:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T16:45:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["regular_minutes"] == 480
    assert data["ot_minutes"] == 45
    assert data["dt_minutes"] == 0


# ─── Immediate consistency (Queue A consistency_model) ──

def test_submit_response_reflects_recomputed_gross_immediately(api):
    """PRD §3.6: "A submit recomputes all derived wage fields from the week's
    punches, breaks, and tips, records the acting supervisor in
    submitted_by_user_id, advances the week DRAFT → SUBMITTED ... and increments
    version by one."

    Design: Corner/consistency_model/submit_response_reflects_recomputed_gross_immediately
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    create_closed_punch(api, employee["id"], worksite["id"],
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z",
                        "2026-06-01T08:00:00Z", "2026-06-01T22:00:00Z")
    week = create_draft_week(api, employee["id"], "2026-06-01")
    resp = api.submit_timesheet_week(week["id"], SUP1)
    data = validate_success(resp, 200)
    # gross is present in the same submit response (no read-after-write lag).
    assert data["gross_wages_cents"] == 36000
    refetched = validate_success(api.get_timesheet_week(week["id"], SUP1), 200)
    assert refetched["gross_wages_cents"] == 36000


# ─── CA: daily and weekly OT not double-counted (Queue B) ──

def test_ca_weekly_no_double_count_with_daily_ot(api):
    """PRD §3.6: "The straight-time pool is those total hours minus the hours the
    daily rule already classified as overtime or double time. Weekly overtime is
    whatever of that straight-time pool exceeds weekly_ot_threshold_hours (default
    40), never below zero."

    Design: Corner/calculations/ca_weekly_no_double_count_with_daily_ot
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    days = [(f"2026-06-0{d}T08:00:00Z", f"2026-06-0{d}T19:00:00Z") for d in (1, 2, 3, 4)]
    employee, _ = setup_multi_day_worker(api, employer, worksite, 2500, days)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    # 4 days x 11h: daily ot = 12h; straight pool 32h < 40 so no weekly extra.
    assert data["regular_minutes"] == 1920
    assert data["ot_minutes"] == 720
    assert data["dt_minutes"] == 0
    assert data["gross_wages_cents"] == 125000


# ─── TX: pure FLSA weekly threshold at 40 (Queue B) ───

def test_flsa_weekly_ot_above_40_hours(api):
    """PRD §3.6: "at a worksite whose rule set leaves daily overtime disabled (the
    FLSA weekly pattern), the daily totals are zero, so overtime is simply the
    weekly hours beyond forty and double time is zero."

    Design: Corner/calculations/flsa_weekly_ot_boundary_at_40
    """
    employer, ruleset, worksite = setup_tx_employer(api)
    days = [(f"2026-06-0{d}T08:00:00Z", f"2026-06-0{d}T18:00:00Z") for d in (1, 2, 3, 4)]
    days.append(("2026-06-05T08:00:00Z", "2026-06-05T14:00:00Z"))  # 6h
    employee, _ = setup_multi_day_worker(api, employer, worksite, 2500, days)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    # 46h total: 40 regular, 6 weekly OT, 0 DT.
    assert data["regular_minutes"] == 2400
    assert data["ot_minutes"] == 360
    assert data["dt_minutes"] == 0
    assert data["gross_wages_cents"] == 122500


# ─── Missed-break premium roll-up (Queue B) ───────────

def test_missed_meal_and_rest_premium_two_hours(api):
    """PRD §3.4: "The week's break_premium_hours is the sum, over every
    workday-and-kind pair in the week, of one for each pair that owes a premium and
    zero otherwise ... and only for a NON_EXEMPT employee whose governing rule set
    enables that kind of premium. Each premium hour is later valued at the
    employee's straight base_rate_cents."

    Design: Corner/calculations/missed_meal_and_rest_break_premium_two_hours
    """
    employer, ruleset, worksite = setup_ca_employer(
        api, ruleset_overrides={"meal_break_premium_enabled": True,
                                "rest_break_premium_enabled": True})
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, _ = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    validate_success(api.create_break_record(
        create_break_record_payload(shift["id"], employee["id"], "MEAL", False), SUP1), 201)
    validate_success(api.create_break_record(
        create_break_record_payload(shift["id"], employee["id"], "REST", False), SUP1), 201)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    assert data["break_premium_hours"] == 2
    # straight 16000 + 2 premium hours * 2000 = 20000
    assert data["gross_wages_cents"] == 20000


# ─── Tipped true-up against minimum wage (Queue B) ────

def test_tip_true_up_makes_up_minimum_wage_shortfall(api):
    """PRD §3.7: "The make-up is the required floor minus what the worker actually
    earned (direct cash plus tips), but never below zero — the employer covers a
    shortfall and never claws back a surplus."

    Design: Corner/calculations/tip_true_up_shortfall_made_up
    """
    employer, ruleset, worksite = setup_tx_employer(
        api, ruleset_overrides={"state_min_wage_cents": 725},
        employer_overrides={"federal_min_wage_cents": 725,
                            "federal_tipped_cash_wage_cents": 213})
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                          base_rate_cents=213, is_tipped=True)
    # 3 x 10h punches = 30h across the week.
    for d in (1, 2, 3):
        create_closed_punch(api, employee["id"], worksite["id"],
                            f"2026-06-0{d}T08:00:00Z", f"2026-06-0{d}T18:00:00Z",
                            f"2026-06-0{d}T08:00:00Z", f"2026-06-0{d}T18:00:00Z")
    validate_success(api.create_tip_declaration(
        create_tip_declaration_payload(employee["id"], "2026-06-01", 10000),
        make_employee_headers(employee["id"])), 201)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    data = submit_week(api, week["id"], SUP1)
    # required = round(725*30) = 21750; direct = 213*30 = 6390; tips 10000;
    # true_up = 21750 - 16390 = 5360; gross = 6390 + 5360 = 11750.
    assert data["regular_minutes"] == 1800
    assert data["tip_true_up_cents"] == 5360
    assert data["gross_wages_cents"] == 11750
