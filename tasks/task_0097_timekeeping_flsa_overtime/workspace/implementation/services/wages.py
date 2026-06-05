"""Weekly timesheet wage computation (PRD §3.6, §3.7; SCAFFOLD §1.3).

The full recompute resolves the dual-variant OT method (CA daily vs FLSA
weekly), the regular rate of pay, break premiums, and the tipped true-up, then
sums gross wages by round-then-sum.

All money is integer cents; durations are integer minutes; hours = minutes/60
treated as an exact ratio during intermediate math (Decimal), rounded only
where the rules call for it, always round_half_up.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

DAILY_OT_THRESHOLD_HOURS = 8
DAILY_DT_THRESHOLD_HOURS = 12
SEVENTH_DAY_FIRST_TIER_HOURS = 8
OT_PREMIUM_MULTIPLIER = Decimal("0.5")
DT_PREMIUM_MULTIPLIER = Decimal("1.0")
DETENTION_GRACE_MINUTES = 15


def round_half_up_cents(value):
    """Round a Decimal to a whole-cent integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _governing_ruleset(employee):
    """The WageRuleSet governing this employee's work, selected by the home
    worksite's (employer_id, state_code) pair (PRD §3.1). None if missing."""
    worksite = db.worksites.get(employee.get("home_worksite_id"))
    if worksite is None:
        return None
    employer_id = employee.get("employer_id")
    state_code = worksite.get("state_code")
    for rs in db.wage_rulesets.values():
        if rs.get("employer_id") == employer_id and rs.get("state_code") == state_code:
            return rs
    return None


def has_governing_ruleset(employee):
    return _governing_ruleset(employee) is not None


def _week_dates(workweek_start):
    """The 7 inclusive calendar dates [workweek_start, workweek_start+6]."""
    start = date.fromisoformat(workweek_start)
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def _week_punches(employee_id, week_dates):
    """The employee's CLOSED, non-VOIDED punches whose workday_date is in
    the workweek."""
    out = []
    for p in db.punches.values():
        if p.get("employee_id") != employee_id:
            continue
        if p.get("status") != "CLOSED":
            continue
        if p.get("workday_date") in week_dates:
            out.append(p)
    return out


def _daily_breakdown(ruleset, week_dates, punches):
    """daily_overtime_breakdown (SCAFFOLD §1.3).

    Returns (daily_regular_h, daily_ot_h, daily_dt_h) as Decimals.
    """
    daily_ot_enabled = bool(ruleset.get("daily_ot_enabled", False))
    ot_threshold = Decimal(str(ruleset.get("daily_ot_threshold_hours", 8)))
    dt_threshold = Decimal(str(ruleset.get("daily_dt_threshold_hours", 12)))
    seventh_enabled = bool(ruleset.get("seventh_day_rule_enabled", False))

    # Sum worked minutes per workday_date.
    per_day_minutes = {}
    for p in punches:
        d = p.get("workday_date")
        per_day_minutes[d] = per_day_minutes.get(d, 0) + p.get("worked_minutes", 0)

    # Determine, for the seventh-day rule, the chronologically-ordered list of
    # worked calendar days within the workweek and which one is the 7th
    # consecutive worked day.
    worked_days_in_order = [d for d in week_dates if per_day_minutes.get(d, 0) > 0]
    seventh_consecutive_day = _seventh_consecutive_worked_day(week_dates, per_day_minutes)

    daily_regular = Decimal(0)
    daily_ot = Decimal(0)
    daily_dt = Decimal(0)

    for d in worked_days_in_order:
        dh = Decimal(per_day_minutes[d]) / Decimal(60)
        if seventh_enabled and d == seventh_consecutive_day:
            day_regular = Decimal(0)
            day_ot = min(dh, Decimal(SEVENTH_DAY_FIRST_TIER_HOURS))
            day_dt = max(Decimal(0), dh - Decimal(SEVENTH_DAY_FIRST_TIER_HOURS))
        elif not daily_ot_enabled:
            day_regular = dh
            day_ot = Decimal(0)
            day_dt = Decimal(0)
        else:
            day_regular = min(dh, ot_threshold)
            day_ot = max(Decimal(0), min(dh, dt_threshold) - ot_threshold)
            day_dt = max(Decimal(0), dh - dt_threshold)
        daily_regular += day_regular
        daily_ot += day_ot
        daily_dt += day_dt

    return daily_regular, daily_ot, daily_dt


def _seventh_consecutive_worked_day(week_dates, per_day_minutes):
    """Return the workday_date that is the 7th consecutive worked calendar day
    within the workweek, or None. The workweek has exactly 7 dates, so this is
    the 7th date only when all seven days were worked."""
    consecutive = 0
    seventh = None
    for d in week_dates:
        if per_day_minutes.get(d, 0) > 0:
            consecutive += 1
            if consecutive == 7:
                seventh = d
        else:
            consecutive = 0
    return seventh


def _weekly_resolution(ruleset, punches, daily_ot_h, daily_dt_h):
    """weekly_overtime_resolution (SCAFFOLD §1.3 / PRD §3.6).

    Returns (regular_minutes, ot_minutes, dt_minutes, total_worked_h).
    """
    weekly_ot_threshold = Decimal(str(ruleset.get("weekly_ot_threshold_hours", 40)))
    total_minutes = sum(p.get("worked_minutes", 0) for p in punches)
    total_worked_h = Decimal(total_minutes) / Decimal(60)

    straight_time_h = total_worked_h - daily_ot_h - daily_dt_h
    weekly_ot_extra_h = max(Decimal(0), straight_time_h - weekly_ot_threshold)
    regular_h = straight_time_h - weekly_ot_extra_h
    ot_h = daily_ot_h + weekly_ot_extra_h
    dt_h = daily_dt_h

    regular_minutes = _hours_to_minutes(regular_h)
    ot_minutes = _hours_to_minutes(ot_h)
    dt_minutes = _hours_to_minutes(dt_h)
    return regular_minutes, ot_minutes, dt_minutes, total_worked_h


def _hours_to_minutes(hours):
    """Multiply hour value by 60 and round to nearest whole minute (PRD §2.5)."""
    return int((Decimal(hours) * Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _regular_rate_cents(base_rate_cents, total_worked_h):
    """regular_rate_of_pay (SCAFFOLD §1.3 / PRD §3.6).

    straight_earnings / total_worked_h, rounded half up to whole cents before
    any premium multiplier. Zero when no hours worked."""
    if total_worked_h <= 0:
        return 0
    straight_earnings = Decimal(base_rate_cents) * total_worked_h
    return round_half_up_cents(straight_earnings / total_worked_h)


def _break_premium_hours(ruleset, employee, week_dates):
    """break_premium_count (SCAFFOLD §1.3 / PRD §3.4).

    At most one premium hour per (workday, kind). Counts break records whose
    shift's scheduled_start date falls inside the workweek, only for a
    NON_EXEMPT employee whose governing rule set enables that kind of premium.
    """
    if employee.get("classification") != "NON_EXEMPT":
        return 0
    meal_enabled = bool(ruleset.get("meal_break_premium_enabled", False))
    rest_enabled = bool(ruleset.get("rest_break_premium_enabled", False))

    # Set of (workday, kind) pairs that owe a premium.
    owed_pairs = set()
    for br in db.break_records.values():
        if br.get("employee_id") != employee["id"]:
            continue
        if br.get("taken", True):
            continue
        kind = br.get("kind")
        if kind == "MEAL" and not meal_enabled:
            continue
        if kind == "REST" and not rest_enabled:
            continue
        shift = db.shifts.get(br.get("shift_id"))
        if shift is None:
            continue
        shift_day = _date_of(shift.get("scheduled_start"))
        if shift_day not in week_dates:
            continue
        owed_pairs.add((shift_day, kind))
    return len(owed_pairs)


def _date_of(iso_dt):
    """The UTC calendar date (YYYY-MM-DD) of an ISO datetime string."""
    if iso_dt is None:
        return None
    s = iso_dt
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _tip_true_up_cents(ruleset, employer, employee, total_worked_h, week_dates):
    """tip_true_up (SCAFFOLD §1.3 / PRD §3.7). Only for is_tipped NON_EXEMPT."""
    if employee.get("classification") != "NON_EXEMPT":
        return 0
    if not employee.get("is_tipped", False):
        return 0

    state_min = ruleset.get("state_min_wage_cents", 725)
    federal_min = employer.get("federal_min_wage_cents", 725)
    applicable_min = max(state_min, federal_min)

    tips_cents = 0
    for td in db.tip_declarations.values():
        if td.get("employee_id") != employee["id"]:
            continue
        if td.get("workday_date") in week_dates:
            tips_cents += td.get("declared_cents", 0)

    base_rate = employee.get("base_rate_cents", 0)
    # required_cents is rounded; direct cash stays exact (rounding happens only
    # where the rules call for it — PRD §2.5). The make-up result is rounded
    # half up to whole cents (scaffold §1.3 precision).
    direct_cash = Decimal(base_rate) * total_worked_h
    required = round_half_up_cents(Decimal(applicable_min) * total_worked_h)
    earned = direct_cash + Decimal(tips_cents)
    shortfall = Decimal(required) - earned
    if shortfall <= 0:
        return 0
    return round_half_up_cents(shortfall)


def recompute_timesheet(week):
    """Recompute all derived wage fields on a TimesheetWeek in place.

    Implements gross_wages (SCAFFOLD §1.3 / PRD §3.6) with the exempt-zeroed
    variant. Does NOT bump version or updated_at — callers control that.
    """
    employee = db.employees.get(week.get("employee_id"))
    week_dates = _week_dates(week["workweek_start"])

    # EXEMPT employees never accrue OT/DT/break premiums — entire stack zeroed.
    if employee is None or employee.get("classification") == "EXEMPT":
        week["regular_minutes"] = 0
        week["ot_minutes"] = 0
        week["dt_minutes"] = 0
        week["break_premium_hours"] = 0
        week["tip_true_up_cents"] = 0
        week["gross_wages_cents"] = 0
        return

    ruleset = _governing_ruleset(employee)
    if ruleset is None:
        # No governing rule set: submit is gated by ERR_NO_WAGE_RULESET before
        # this runs, so treat as a zeroed stack defensively.
        week["regular_minutes"] = 0
        week["ot_minutes"] = 0
        week["dt_minutes"] = 0
        week["break_premium_hours"] = 0
        week["tip_true_up_cents"] = 0
        week["gross_wages_cents"] = 0
        return

    punches = _week_punches(employee["id"], week_dates)

    daily_regular_h, daily_ot_h, daily_dt_h = _daily_breakdown(ruleset, week_dates, punches)
    regular_minutes, ot_minutes, dt_minutes, total_worked_h = _weekly_resolution(
        ruleset, punches, daily_ot_h, daily_dt_h
    )

    base_rate = employee.get("base_rate_cents", 0)
    regular_rate = _regular_rate_cents(base_rate, total_worked_h)

    break_premium_hours = _break_premium_hours(ruleset, employee, week_dates)

    employer = db.employers.get(employee.get("employer_id"), {})
    tip_true_up = _tip_true_up_cents(ruleset, employer, employee, total_worked_h, week_dates)

    # gross_wages: round each component to whole cents, then sum (round-then-sum
    # order is PINNED).
    straight_cents = round_half_up_cents(Decimal(base_rate) * total_worked_h)
    ot_premium_cents = round_half_up_cents(
        Decimal(regular_rate) * OT_PREMIUM_MULTIPLIER * (Decimal(ot_minutes) / Decimal(60))
    )
    dt_premium_cents = round_half_up_cents(
        Decimal(regular_rate) * DT_PREMIUM_MULTIPLIER * (Decimal(dt_minutes) / Decimal(60))
    )
    break_premium_cents = break_premium_hours * base_rate
    gross = (straight_cents + ot_premium_cents + dt_premium_cents
             + break_premium_cents + tip_true_up)

    week["regular_minutes"] = regular_minutes
    week["ot_minutes"] = ot_minutes
    week["dt_minutes"] = dt_minutes
    week["break_premium_hours"] = break_premium_hours
    week["tip_true_up_cents"] = tip_true_up
    week["gross_wages_cents"] = gross
