"""Business logic: calculations, cascading state transitions, eligibility,
carrier-feed emission, and the payroll/retro deduction ledger.

Every behavioral rule here traces to a sentence in PRD §3 (and SCAFFOLD §1.2/§1.3).
"""
from __future__ import annotations

import calendar
from datetime import timedelta

import clock
import db
from services import common as C


# ============================================================================
# Constants (SCAFFOLD §1.3)
# ============================================================================
SEMI_MONTHLY_PERIODS = 24
BIWEEKLY_PERIODS = 26
ACA_AFFORDABILITY_PCT = "0.0902"  # decimal factor (PRD §3.10)
LIFE_EVENT_WINDOW_DAYS = 30


# ============================================================================
# Catalog lookups
# ============================================================================
def offering_for_tier(tier: dict) -> dict:
    return db.plan_offerings.get(tier["plan_offering_id"])


def benefit_type_for_tier(tier: dict) -> str:
    off = offering_for_tier(tier)
    return off["benefit_type"] if off else None


# ============================================================================
# Calculations (SCAFFOLD §1.3 / PRD §3.5, §3.8, §3.10)
# ============================================================================
def compute_monthly_employee_cost(enrollment: dict, tier: dict) -> int:
    """PRD §3.5 / calc compute_monthly_employee_cost.

    Non-life: employer_share rounded BEFORE subtraction.
    VOLUNTARY_LIFE: units * rate_per_1000, rounded half up.
    """
    benefit_type = enrollment["benefit_type"]
    if benefit_type in ("MEDICAL", "DENTAL", "VISION"):
        premium = tier["monthly_premium_cents"]
        employer_share = C.round_half_up(
            _dec(premium) * _dec(tier["employer_contribution_pct"])
        )
        return premium - employer_share
    elif benefit_type == "VOLUNTARY_LIFE":
        units = _dec(enrollment.get("coverage_amount_cents", 0)) / _dec(100000)
        return C.round_half_up(units * _dec(tier["rate_per_1000_monthly_cents"]))
    return 0


def compute_per_paycheck_deduction(monthly_employee_cost_cents: int, employee: dict) -> int:
    """PRD §3.5 / calc compute_per_paycheck_deduction.

    annualize-then-divide: multiply by 12 BEFORE dividing by periods.
    """
    periods = (
        SEMI_MONTHLY_PERIODS
        if employee["payroll_schedule"] == "SEMI_MONTHLY"
        else BIWEEKLY_PERIODS
    )
    annual = _dec(monthly_employee_cost_cents) * _dec(12)
    return C.round_half_up(annual / _dec(periods))


def recompute_enrollment_costs(enrollment: dict, employee: dict) -> None:
    tier = db.plan_tiers[enrollment["plan_tier_id"]]
    mec = compute_monthly_employee_cost(enrollment, tier)
    enrollment["monthly_employee_cost_cents"] = mec
    enrollment["per_paycheck_deduction_cents"] = compute_per_paycheck_deduction(mec, employee)


def reconcile_carrier_premium(enrollment: dict) -> int:
    """PRD §3.8 / calc reconcile_carrier_premium.

    Round each prorated component line FIRST, THEN sum (order pinned).
    """
    tier = db.plan_tiers[enrollment["plan_tier_id"]]
    start = C.parse_iso(enrollment["coverage_start_date"])
    d = C.date_of(start)
    days_in_month = calendar.monthrange(d.year, d.month)[1]
    days_covered = days_in_month - d.day + 1

    premium = tier["monthly_premium_cents"]
    employer_monthly = C.round_half_up(_dec(premium) * _dec(tier["employer_contribution_pct"]))
    employee_monthly = premium - employer_monthly

    prorated_employer = C.round_half_up(_dec(employer_monthly) * _dec(days_covered) / _dec(days_in_month))
    prorated_employee = C.round_half_up(_dec(employee_monthly) * _dec(days_covered) / _dec(days_in_month))
    return prorated_employer + prorated_employee


def compute_aca_affordability(employee: dict, lowest_cost_tier: dict):
    """PRD §3.10 / calc compute_aca_affordability. Returns a 3-tuple."""
    premium = lowest_cost_tier["monthly_premium_cents"]
    employer_share = C.round_half_up(_dec(premium) * _dec(lowest_cost_tier["employer_contribution_pct"]))
    lowest_cost_monthly = premium - employer_share
    threshold = C.round_half_up(
        _dec(employee["monthly_household_income_cents"]) * _dec(ACA_AFFORDABILITY_PCT)
    )
    indicator = "AFFORDABLE" if lowest_cost_monthly <= threshold else "UNAFFORDABLE"
    return lowest_cost_monthly, threshold, indicator


# ============================================================================
# Carrier feed emission (PRD §3.8)
# ============================================================================
def emit_carrier_feed(enrollment: dict, transaction_set: str) -> dict:
    rec = C.new_lean_fields()
    rec.update({
        "enrollment_id": enrollment["id"],
        "transaction_set": transaction_set,
        "reconciled_monthly_premium_cents": reconcile_carrier_premium(enrollment),
    })
    db.carrier_feed_records[rec["id"]] = rec
    return rec


# ============================================================================
# Deduction lines (PRD §3.7)
# ============================================================================
def post_regular_deduction(enrollment: dict, employee: dict, pay_period_index: int) -> dict:
    line = C.new_lean_fields()
    line.update({
        "enrollment_id": enrollment["id"],
        "employee_id": employee["id"],
        "pay_period_index": pay_period_index,
        "line_type": "REGULAR",
        "amount_cents": enrollment["per_paycheck_deduction_cents"],
        # internal: clock date on which this period was billed (drives retro test)
        "_billed_date": clock.now().date().isoformat(),
    })
    db.deduction_lines[line["id"]] = line
    return line


def post_retro_adjustment(enrollment: dict, employee: dict, pay_period_index: int, amount_cents: int) -> dict:
    line = C.new_lean_fields()
    line.update({
        "enrollment_id": enrollment["id"],
        "employee_id": employee["id"],
        "pay_period_index": pay_period_index,
        "line_type": "RETRO_ADJUSTMENT",
        "amount_cents": amount_cents,
        "_billed_date": clock.now().date().isoformat(),
    })
    db.deduction_lines[line["id"]] = line
    return line


# ============================================================================
# Eligibility / clock (PRD §2.7, §3.1)
# ============================================================================
def advance_clock_and_reevaluate(target_dt) -> None:
    """Set the logical clock, elapse crossed waiting periods, bubble eligibility."""
    clock.set_clock(target_dt)
    now = clock.now()
    for wp in db.waiting_periods.values():
        if wp["status"] != "PENDING":
            continue
        end = C.parse_iso(wp["end_date"])
        if now >= end:
            wp["status"] = "ELAPSED"
            C.touch(wp)
            emp = db.employees.get(wp["employee_id"])
            if emp is None:
                continue
            if emp["employment_type"] != "SEASONAL" and emp["eligibility_status"] == "WAITING":
                emp["eligibility_status"] = "ELIGIBLE"
                C.touch(emp)


# ============================================================================
# Enrollment supersede cascade (PRD §3.1 termination, §3.6 life event)
# ============================================================================
def supersede_enrollment(old: dict, coverage_end_date_str: str, superseding_id):
    """Move an ACTIVE enrollment -> SUPERSEDED; set end date + linkage; emit TERM."""
    old["status"] = "SUPERSEDED"
    old["coverage_end_date"] = coverage_end_date_str
    if superseding_id is not None:
        old["superseded_by_enrollment_id"] = superseding_id
    C.touch(old)
    emit_carrier_feed(old, "TERM")


def active_enrollment_of_benefit_type(employee_id: str, benefit_type: str):
    for e in db.enrollments.values():
        if (e["employee_id"] == employee_id
                and e["benefit_type"] == benefit_type
                and e["status"] == "ACTIVE"):
            return e
    return None


# ============================================================================
# Coverage interval overlap (PRD §3.4)
# ============================================================================
def coverage_intervals_overlap(start_a, end_a, start_b, end_b) -> bool:
    """Closed inclusive intervals. end may be None (open-ended ACTIVE).

    Adjacency (prev_end + 1 day == start) is allowed (not an overlap).
    """
    # Open-ended -> treat as +infinity.
    if end_a is None:
        end_a = _MAX_DATE
    if end_b is None:
        end_b = _MAX_DATE
    # Closed inclusive overlap: a.start <= b.end and b.start <= a.end.
    return start_a <= end_b and start_b <= end_a


# ============================================================================
# Helpers
# ============================================================================
def _dec(v):
    from decimal import Decimal
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


from datetime import date as _date
_MAX_DATE = _date(9999, 12, 31)


def date_minus_one_day_str(date_str: str) -> str:
    d = C.date_of(C.parse_iso(date_str))
    return (d - timedelta(days=1)).isoformat()
