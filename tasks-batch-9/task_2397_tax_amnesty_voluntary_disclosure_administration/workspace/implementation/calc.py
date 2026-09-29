"""Named calculation rules and their constants (SCAFFOLD 1.3, PRD 2.7).

Money is exact integer cents.  Every rate multiplication is carried in Decimal
and converted to cents by ROUND_HALF_UP exactly once, at the point named by the
rule that produces the value.  Percentages carry four decimal places and are
never rounded to cents here.
"""

import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

# --- return_statutory_liability ------------------------------------------------
TIER_1_MAX_DAYS_LATE = 90
TIER_2_MAX_DAYS_LATE = 365
PENALTY_RATE_TIER_1 = Decimal("0.05")
PENALTY_RATE_TIER_2 = Decimal("0.15")
PENALTY_RATE_TIER_3 = Decimal("0.25")
NONFILER_SURCHARGE_RATE = Decimal("0.05")
DAILY_INTEREST_RATE = Decimal("0.00025")

# --- agreement_effective_waiver_resolution ------------------------------------
HAIRCUT_TIER_1_MIN_CENTS = 5000000
HAIRCUT_TIER_1_PCT = Decimal("0.10")
HAIRCUT_TIER_2_MIN_CENTS = 25000000
HAIRCUT_TIER_2_PCT = Decimal("0.25")

# --- installment_schedule_generation ------------------------------------------
INSTALLMENT_PERIOD_DAYS = 30
INSTALLMENT_HORIZON_DAYS = 365
MIN_INSTALLMENT_CENTS = 2500
MIN_DOWN_PAYMENT_PCT = Decimal("0.10")
INSTALLMENT_GRACE_DAYS_LATE = 30

# --- post_program_penalty_assessment ------------------------------------------
TIER_RATE_T0 = Decimal("0.10")
TIER_RATE_T1 = Decimal("0.20")
TIER_RATE_T2 = Decimal("0.35")
BEHAVIOR_SCORE_FLOOR = 60
BEHAVIOR_ADJUSTMENT_RATE = Decimal("0.05")
PENALTY_CAP_PCT = Decimal("0.50")
PENALTY_FLOOR_CENTS = 10000

# --- taxpayer_compliance_behavior_score ---------------------------------------
SCORE_BASE = 100
OPEN_CASE_PENALTY = 20
REFERRED_CASE_PENALTY = 30
NONFILER_PERIOD_PENALTY = 5
NONPARTICIPANT_PENALTY = 25
ISSUED_ACTION_PENALTY = 8
FULFILLED_AGREEMENT_CREDIT = 15
PROGRAM_PARTICIPATION_CREDIT = 18

# --- taxpayer_escalation_tier_resolution --------------------------------------
T2_MIN_OPEN_CASES = 1

# --- program_revenue_realization ----------------------------------------------
ON_TRACK_MIN_PCT = Decimal("0.9000")
WATCH_MIN_PCT = Decimal("0.7000")

# --- negotiation ---------------------------------------------------------------
MAX_REPRESENTATIVE_COUNTERS = 3


def dec(value):
    """Coerce a stored number (int / float / Decimal / None) to Decimal."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu_cents(value):
    """Round half up to a whole number of cents."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q4(value):
    """Quantize a percentage to four decimal places, rounding half up."""
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def pct_out(value):
    """Render a percentage for JSON output."""
    if value is None:
        return None
    return float(q4(value))


def add_months(anchor, months):
    """Shift a date or datetime by whole months, clamping the day of month."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    if isinstance(anchor, datetime):
        return anchor.replace(year=year, month=month, day=day)
    return date(year, month, day)


# ------------------------------------------------------------------ liability
def tier_rate(days_late):
    if days_late <= TIER_1_MAX_DAYS_LATE:
        return PENALTY_RATE_TIER_1
    if days_late <= TIER_2_MAX_DAYS_LATE:
        return PENALTY_RATE_TIER_2
    return PENALTY_RATE_TIER_3


def statutory_liability(reported_tax_cents, original_due_date, accrual_end_date, is_nonfiler_period):
    """return_statutory_liability: the shared tail of both variants."""
    days_late = (accrual_end_date - original_due_date).days
    if days_late < 0:
        days_late = 0
    rate = tier_rate(days_late)
    if is_nonfiler_period:
        rate = rate + NONFILER_SURCHARGE_RATE
    gross_penalty = rhu_cents(dec(reported_tax_cents) * rate)
    gross_interest = rhu_cents(dec(reported_tax_cents) * DAILY_INTEREST_RATE * dec(days_late))
    return days_late, rate, gross_penalty, gross_interest


def haircut_for(gross_liability_cents):
    """Step 3 of agreement_effective_waiver_resolution; both bounds inclusive."""
    if gross_liability_cents >= HAIRCUT_TIER_2_MIN_CENTS:
        return HAIRCUT_TIER_2_PCT
    if gross_liability_cents >= HAIRCUT_TIER_1_MIN_CENTS:
        return HAIRCUT_TIER_1_PCT
    return Decimal("0.00")


def effective_waivers(base_penalty_pct, base_interest_pct, haircut_pct):
    """Step 4: the haircut bites penalty at full strength, interest at half."""
    zero = Decimal("0.00")
    penalty = dec(base_penalty_pct) - dec(haircut_pct)
    interest = dec(base_interest_pct) - (dec(haircut_pct) / Decimal(2))
    return q4(max(zero, penalty)), q4(max(zero, interest))


# ------------------------------------------------------------------- schedule
def schedule_amounts(schedulable_cents, installment_count):
    """installment_schedule_generation: the last row absorbs the remainder."""
    base_amount = schedulable_cents // installment_count
    amounts = [base_amount for _ in range(installment_count - 1)]
    amounts.append(schedulable_cents - base_amount * (installment_count - 1))
    return amounts


def min_down_payment_cents(total_due_cents):
    return rhu_cents(dec(total_due_cents) * MIN_DOWN_PAYMENT_PCT)


# ------------------------------------------------------------------- penalties
def tier_rate_for_escalation(escalation_tier):
    if escalation_tier == "T2":
        return TIER_RATE_T2
    if escalation_tier == "T1":
        return TIER_RATE_T1
    return TIER_RATE_T0


def post_program_penalty(base_tax_cents, escalation_tier, behavior_adjustment, multiplier):
    """The cap is applied first and the floor last, on already-rounded integers."""
    rate = tier_rate_for_escalation(escalation_tier) + dec(behavior_adjustment)
    raw_cents = rhu_cents(dec(base_tax_cents) * rate * dec(multiplier))
    cap_cents = rhu_cents(dec(base_tax_cents) * PENALTY_CAP_PCT)
    return max(PENALTY_FLOOR_CENTS, min(raw_cents, cap_cents))


def clamp_score(score):
    return max(0, min(100, score))


# --------------------------------------------------------------- realization
def realization_pct(collected_cents, revenue_forecast_cents):
    if not revenue_forecast_cents:
        return q4(0)
    return q4(dec(collected_cents) / dec(revenue_forecast_cents))


def forecast_status(rounded_pct):
    if rounded_pct >= ON_TRACK_MIN_PCT:
        return "ON_TRACK"
    if rounded_pct >= WATCH_MIN_PCT:
        return "WATCH"
    return "SHORTFALL"


def mean_score(scores):
    if not scores:
        return 0
    return rhu_cents(dec(sum(scores)) / dec(len(scores)))
