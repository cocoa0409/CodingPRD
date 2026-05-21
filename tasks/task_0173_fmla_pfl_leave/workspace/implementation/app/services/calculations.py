"""Calculation rules — §1.3.

All money math is integer cents with round-half-up at every named step.
All hours math is whole integers, remaining floored at zero.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

# --- Constants ---
MIN_MONTHS_SERVICE = 12
MIN_HOURS_TRAILING = 1250
MIN_HEADCOUNT_75MI = 50

FMLA_ENTITLEMENT_HOURS = 480
WORKWEEK_HOURS = 40

WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12
REPLACEMENT_RATIO = Decimal("0.60")
PFL_WEEKLY_CAP_CENTS = 162_900  # $1,629.00

JOB_RESTORATION_FLOOR = 50
INSUFF_MULTIPLIER = Decimal("0.50")
FORFEIT_MULTIPLIER = Decimal("0.00")
GRACE_MULTIPLIER = Decimal("0.75")
TENURE_BONUS_MULTIPLIER = Decimal("1.10")
MAX_SCORE = 100


def round_half_up_int(value: Decimal) -> int:
    """Round a Decimal half-up to a whole integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -----------------------------------------------------------------------------
# eligibility_calc
# -----------------------------------------------------------------------------
def months_of_service(hire_date_iso: str, now: datetime) -> int:
    """Whole calendar months between hire_date and now, floored.

    A hire date on the same day-of-month exactly N months earlier yields N.
    The day-of-month boundary matters: if `now`'s day is at least the hire-date day,
    the boundary has been reached.
    """
    hire = _parse_date(hire_date_iso)
    today = now.date()
    months = (today.year - hire.year) * 12 + (today.month - hire.month)
    if today.day < hire.day:
        months -= 1
    return max(0, months)


def evaluate_eligibility(employee: dict, worksite: dict, now: datetime) -> Tuple[bool, str | None, dict]:
    """Return (eligible, failing_reason_code, details).

    Reason codes are evaluated in the priority order tenure -> hours -> worksite
    so the first failing threshold wins.
    """
    months = months_of_service(employee["hire_date"], now)
    hours = int(employee.get("hours_worked_trailing_12mo", 0))
    headcount = int(worksite.get("employee_count_within_75_miles", 0))

    details = {
        "months_of_service": months,
        "hours_trailing": hours,
        "worksite_headcount": headcount,
    }

    if months < MIN_MONTHS_SERVICE:
        return False, "ERR_NOT_ELIGIBLE_TENURE", details
    if hours < MIN_HOURS_TRAILING:
        return False, "ERR_NOT_ELIGIBLE_HOURS", details
    if headcount < MIN_HEADCOUNT_75MI:
        return False, "ERR_NOT_ELIGIBLE_WORKSITE", details
    return True, None, details


# -----------------------------------------------------------------------------
# quota_balance_calc
# -----------------------------------------------------------------------------
def window_for_basis(leave_year_basis: str, anchor_date: date) -> Tuple[date, date]:
    """Return (window_start, window_end) inclusive for the leave-year window.

    CALENDAR: Jan 1 — Dec 31 of anchor_date's year.
    ROLLING_BACKWARD: (anchor_date - 365 days, anchor_date) inclusive.
    """
    if leave_year_basis == "CALENDAR":
        return date(anchor_date.year, 1, 1), date(anchor_date.year, 12, 31)
    if leave_year_basis == "ROLLING_BACKWARD":
        return anchor_date - timedelta(days=365), anchor_date
    raise ValueError(f"Unknown leave_year_basis: {leave_year_basis}")


def consumed_hours_in_window(
    store,
    employee_id: str,
    window_start: date,
    window_end: date,
    exclude_case_id: str | None = None,
) -> int:
    """Sum hours_used for APPROVED LeaveInstances whose owning LeaveCase is in
    {APPROVED, ACTIVE, COMPLETED, JOB_RESTORED} and whose instance_date is inside
    the window (inclusive on both ends)."""
    valid_case_statuses = {"APPROVED", "ACTIVE", "COMPLETED", "JOB_RESTORED"}
    total = 0
    for case in store.leave_cases.values():
        if case["employee_id"] != employee_id:
            continue
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if case["case_status"] not in valid_case_statuses:
            continue
        for inst in store.leave_instances.values():
            if inst["leave_case_id"] != case["id"]:
                continue
            if inst["instance_status"] != "APPROVED":
                continue
            inst_date = _parse_date(inst["instance_date"])
            if window_start <= inst_date <= window_end:
                total += int(inst["hours_used"])
    return total


def remaining_hours_for_employee(
    store,
    employee_id: str,
    leave_year_basis: str,
    anchor_date: date,
    exclude_case_id: str | None = None,
) -> Tuple[int, int, date, date]:
    """Return (consumed_hours, remaining_hours, window_start, window_end)."""
    window_start, window_end = window_for_basis(leave_year_basis, anchor_date)
    consumed = consumed_hours_in_window(
        store,
        employee_id,
        window_start,
        window_end,
        exclude_case_id=exclude_case_id,
    )
    remaining = max(0, FMLA_ENTITLEMENT_HOURS - consumed)
    return consumed, remaining, window_start, window_end


# -----------------------------------------------------------------------------
# pfl_weekly_benefit_calc
# -----------------------------------------------------------------------------
def pfl_weekly_benefit(monthly_wage_cents: int) -> int:
    if monthly_wage_cents <= 0:
        return 0
    # Step 1: weekly_wage = round_half_up(monthly * 12 / 52)
    weekly_wage = round_half_up_int(Decimal(monthly_wage_cents) * Decimal(MONTHS_PER_YEAR) / Decimal(WEEKS_PER_YEAR))
    # Step 2: apply replacement ratio with rounding
    raw_weekly_benefit = round_half_up_int(Decimal(weekly_wage) * REPLACEMENT_RATIO)
    # Step 3: apply cap
    return min(raw_weekly_benefit, PFL_WEEKLY_CAP_CENTS)


# -----------------------------------------------------------------------------
# benefit_invoice_calc
# -----------------------------------------------------------------------------
def days_on_leave_in_month(
    store,
    case: dict,
    year: int,
    month: int,
) -> int:
    """Compute the days-on-leave count for the given calendar month.

    Continuous cases: bridge days between max(requested_start_date, first_of_month)
    and min(expected_end_date, last_of_month) inclusive.
    Intermittent / reduced-schedule cases: count of LeaveInstance rows on this case
    whose instance_status is in {APPROVED, PROPOSED} and whose instance_date falls
    inside the month.
    """
    first = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    last = date(year, month, last_day)

    if case["leave_pattern"] == "CONTINUOUS":
        req_start = _parse_date(case["requested_start_date"])
        exp_end = _parse_date(case["expected_end_date"])
        bridge_start = max(req_start, first)
        bridge_end = min(exp_end, last)
        if bridge_end < bridge_start:
            return 0
        return (bridge_end - bridge_start).days + 1

    # INTERMITTENT or REDUCED_SCHEDULE — count instance rows in the month
    count = 0
    for inst in store.leave_instances.values():
        if inst["leave_case_id"] != case["id"]:
            continue
        if inst["instance_status"] not in {"APPROVED", "PROPOSED"}:
            continue
        d = _parse_date(inst["instance_date"])
        if first <= d <= last:
            count += 1
    return count


def benefit_invoice_amount(
    store,
    case: dict,
    employer: dict,
    year: int,
    month: int,
) -> int:
    """Return amount_due_cents for the given case/month."""
    days_in_month = monthrange(year, month)[1]
    days_on_leave = days_on_leave_in_month(store, case, year, month)
    premium_share = int(employer.get("benefit_premium_share_cents", 0))
    if days_in_month <= 0 or days_on_leave <= 0 or premium_share <= 0:
        return 0
    amount = Decimal(premium_share) * Decimal(days_on_leave) / Decimal(days_in_month)
    return round_half_up_int(amount)


# -----------------------------------------------------------------------------
# job_restoration_score
# -----------------------------------------------------------------------------
def job_restoration_score_and_status(
    store,
    case: dict,
    employee: dict,
) -> Tuple[int, str]:
    """Compute the job-restoration score and the derived status.

    DENIED case: returns (0, NOT_APPLICABLE) regardless of score.
    """
    if case["case_status"] == "DENIED":
        return 0, "NOT_APPLICABLE"

    score = Decimal(MAX_SCORE)
    # Step 1: cert penalty
    if case.get("certification_status") == "INSUFFICIENT":
        score = Decimal(round_half_up_int(score * INSUFF_MULTIPLIER))

    # Step 2: invoice penalty
    any_forfeited = False
    any_grace = False
    for inv in store.benefit_invoices.values():
        if inv["leave_case_id"] != case["id"]:
            continue
        if inv["invoice_status"] == "FORFEITED":
            any_forfeited = True
            break
        if inv["invoice_status"] == "GRACE":
            any_grace = True
    if any_forfeited:
        score = Decimal(round_half_up_int(score * FORFEIT_MULTIPLIER))
    elif any_grace:
        score = Decimal(round_half_up_int(score * GRACE_MULTIPLIER))

    # Step 3: tenure bonus, then clamp
    if int(employee.get("hours_worked_trailing_12mo", 0)) >= 2000:
        score = Decimal(round_half_up_int(score * TENURE_BONUS_MULTIPLIER))
    score_int = round_half_up_int(score)
    if score_int > MAX_SCORE:
        score_int = MAX_SCORE
    if score_int < 0:
        score_int = 0

    status = "PROTECTED" if score_int >= JOB_RESTORATION_FLOOR else "FORFEITED"
    return score_int, status


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _parse_date(iso: str) -> date:
    return date.fromisoformat(iso[:10])
