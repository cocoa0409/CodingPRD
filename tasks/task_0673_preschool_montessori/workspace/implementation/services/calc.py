"""Calculation rules (SCAFFOLD §1.3, PRD §3.3/§3.6/§3.8, §2.7/§2.8).

All money is integer cents. Fractional cents are rounded half up
(decimal.ROUND_HALF_UP). Counts use ceiling where the spec requires rounding
up. Never use float for money.
"""
import calendar
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db, parse_iso

# Constants — verbatim from SCAFFOLD §1.3.
SIBLING_DISCOUNT_PCT = Decimal("0.10")
FINANCIAL_AID_FLOOR_CENTS = 300000
SIBLING_WEIGHT = 1000
STAFF_CHILD_WEIGHT = 1500
DAYS_WEIGHT = 1
TENURE_CAP_DAYS = 365
LEVEL_RATIO = {"TODDLER": 6, "PRIMARY": 10, "ELEMENTARY": 12}


def round_half_up(value):
    """Round a numeric/Decimal value half-up to the nearest whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Sibling helper: "a Student that has an Enrollment with placement_status PLACED"
# ---------------------------------------------------------------------------
def sibling_has_placed_enrollment(student):
    sibling_id = student.get("sibling_of_student_id")
    if not sibling_id:
        return False
    if sibling_id not in db.students:
        return False
    for enr in db.enrollments.values():
        if enr["student_id"] == sibling_id and enr["placement_status"] == "PLACED":
            return True
    return False


# ---------------------------------------------------------------------------
# tuition_net + monthly_installment (SCAFFOLD calc tuition_net, PRD §3.6)
# Pinned order: sibling discount -> extended-day add-on -> financial aid.
# ---------------------------------------------------------------------------
def compute_tuition_net(tier, student, enrollment_ext_day, financial_aid_pct):
    net = Decimal(tier["base_annual_cents"])

    # step1: sibling discount
    if sibling_has_placed_enrollment(student):
        net = Decimal(round_half_up(net * (Decimal(1) - SIBLING_DISCOUNT_PCT)))

    # step2: extended-day surcharge
    if enrollment_ext_day:
        net = net + Decimal(tier["extended_day_annual_cents"])

    # step3: financial aid (applied LAST, then floored)
    aid = Decimal(str(financial_aid_pct))
    if aid > 0:
        net = Decimal(round_half_up(net * (Decimal(1) - aid)))
        if net < FINANCIAL_AID_FLOOR_CENTS:
            net = Decimal(FINANCIAL_AID_FLOOR_CENTS)

    net_annual = int(net)
    monthly = round_half_up(Decimal(net_annual) / Decimal(tier["installments"]))
    return net_annual, monthly


def compute_deposit(tier):
    # Deposit off base_annual_cents only; ignores all adjustments (PRD §3.6).
    return round_half_up(Decimal(tier["base_annual_cents"]) * Decimal(str(tier["deposit_pct"])))


# ---------------------------------------------------------------------------
# paid_to_date (SCAFFOLD calc paid_to_date, PRD §3.7) — exact sum of CAPTURED.
# ---------------------------------------------------------------------------
def compute_paid_to_date(enrollment_id):
    return sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["enrollment_id"] == enrollment_id and p["status"] == "CAPTURED"
    )


# ---------------------------------------------------------------------------
# waitlist_priority (SCAFFOLD calc waitlist_priority, PRD §3.3)
# ---------------------------------------------------------------------------
def compute_priority_score(application, student):
    waitlisted_at = application.get("waitlisted_at")
    tenure = 0
    if waitlisted_at:
        delta = db.clock_now() - parse_iso(waitlisted_at)
        days_on_waitlist = math.floor(delta.total_seconds() / 86400)
        if days_on_waitlist < 0:
            days_on_waitlist = 0
        tenure = min(TENURE_CAP_DAYS, days_on_waitlist) * DAYS_WEIGHT

    sibling_component = SIBLING_WEIGHT if sibling_has_placed_enrollment(student) else 0
    staff_component = STAFF_CHILD_WEIGHT if student.get("staff_child") else 0
    return sibling_component + staff_component + tenure


# ---------------------------------------------------------------------------
# ratio_compliance (SCAFFOLD calc ratio_compliance, PRD §2.8)
# ---------------------------------------------------------------------------
def compute_compliance_status(level, placed_count, assigned_staff_count, capacity):
    ratio = LEVEL_RATIO[level]
    required_staff = 0 if placed_count == 0 else math.ceil(placed_count / ratio)
    if placed_count > capacity:
        return "OVER_CAPACITY"
    if assigned_staff_count < required_staff:
        return "OVER_RATIO"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# refund_amount (SCAFFOLD calc refund_amount, PRD §3.8)
# ---------------------------------------------------------------------------
def _months_started_forward(program_start, effective):
    """Count calendar months M where program_start <= effective AND the first
    of month M is <= effective. Months range over [program_start_month,
    effective_month] inclusive when the start condition holds."""
    if program_start > effective:
        return 0
    start_y, start_m = program_start.year, program_start.month
    eff_y, eff_m = effective.year, effective.month
    # All months from the program-start month through the effective month have
    # their first day <= effective (since first-of-effective-month <= effective
    # and earlier months' firsts are even earlier).
    return (eff_y - start_y) * 12 + (eff_m - start_m) + 1


def _full_months_chronological(program_start, effective):
    """Calendar months strictly before the withdrawal (effective) month and on
    or after the program-start month."""
    if program_start > effective:
        return 0
    start_y, start_m = program_start.year, program_start.month
    eff_y, eff_m = effective.year, effective.month
    months_in_window = (eff_y - start_y) * 12 + (eff_m - start_m)
    # months_in_window counts months from start month up to (not including)
    # the withdrawal month, i.e. the fully-earned months.
    return max(0, months_in_window)


def compute_refund(enrollment, effective_date_iso, method):
    monthly = enrollment["monthly_installment_cents"]
    deposit_nonref = enrollment["deposit_cents"]
    paid = enrollment["paid_to_date_cents"]

    program_start = parse_iso(enrollment["program_start_date"])
    effective = parse_iso(effective_date_iso)

    if method == "FORWARD":
        n_forward = _months_started_forward(program_start, effective)
        earned = deposit_nonref + n_forward * monthly
    else:  # CHRONOLOGICAL
        n_full = _full_months_chronological(program_start, effective)
        attended_days = effective.day  # inclusive, 1-based day-of-month
        days_in_month = calendar.monthrange(effective.year, effective.month)[1]
        prorated = round_half_up(Decimal(monthly) * Decimal(attended_days) / Decimal(days_in_month))
        earned = deposit_nonref + n_full * monthly + prorated

    refund_cents = max(0, paid - earned)
    balance_due_cents = max(0, earned - paid)
    return earned, refund_cents, balance_due_cents


def months_between_for_age(dob_iso, now_dt):
    """Age in whole months from date_of_birth to the logical clock (PRD §3.1)."""
    dob = parse_iso(dob_iso)
    months = (now_dt.year - dob.year) * 12 + (now_dt.month - dob.month)
    # Subtract one if the day-of-month boundary hasn't been reached yet.
    if (now_dt.day, now_dt.hour, now_dt.minute, now_dt.second) < (
        dob.day, dob.hour, dob.minute, dob.second
    ):
        months -= 1
    return months
