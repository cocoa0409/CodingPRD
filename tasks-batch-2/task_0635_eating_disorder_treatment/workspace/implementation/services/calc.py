"""Calculation rules (PRD §3 and SCAFFOLD Table 3).

All precision-sensitive arithmetic uses decimal.Decimal with ROUND_HALF_UP.
Every threshold is an inclusive lower bound (>=) per PRD §2.9.
"""
from decimal import Decimal, ROUND_HALF_UP

from clock import SECONDS_PER_DAY

# ---- Constants (verbatim from SCAFFOLD Table 3 / PRD §3) ----
W_MEDICAL = Decimal("0.40")
W_BEHAVIORAL = Decimal("0.30")
W_PSYCHIATRIC = Decimal("0.20")
W_MOTIVATION = Decimal("0.10")  # subtracted
T_RESIDENTIAL = Decimal("70")
T_PHP = Decimal("50")
T_IOP = Decimal("30")

BMI_SEVERE_BONUS = Decimal("15")
BMI_MODERATE_BONUS = Decimal("7")
MEDICAL_HOLD_RISK_BUMP = Decimal("10")
MEAL_CREDIT_FACTOR = Decimal("40")

T_UNSTABLE = Decimal("75")
T_GUARDED = Decimal("50")

W_GOALS = Decimal("0.45")
W_MEALS = Decimal("0.35")
W_STABILITY = Decimal("0.20")
STEP_DOWN_THRESHOLD = Decimal("75")
MEAL_COMPLIANCE_FLOOR = Decimal("0.80")
MIN_MEALS_FOR_STEP_DOWN = 3

LOC_LADDER = ["RESIDENTIAL", "PHP", "IOP", "OP"]


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round4(d):
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _clamp(d, lo, hi):
    if d < lo:
        return lo
    if d > hi:
        return hi
    return d


def _to_number(d):
    """Return a Decimal as int when integral, else float, for JSON output."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# recommended_level_of_care (PRD §3.2)
# ---------------------------------------------------------------------------
def composite_score(medical, behavioral, psychiatric, motivation):
    raw = (
        W_MEDICAL * (Decimal(medical) * 10)
        + W_BEHAVIORAL * (Decimal(behavioral) * 10)
        + W_PSYCHIATRIC * (Decimal(psychiatric) * 10)
        - W_MOTIVATION * (Decimal(motivation) * 10)
    )
    rounded = _round2(raw)
    return _clamp(rounded, Decimal("0"), Decimal("100"))


def recommended_loc(score):
    if score >= T_RESIDENTIAL:
        return "RESIDENTIAL"
    if score >= T_PHP:
        return "PHP"
    if score >= T_IOP:
        return "IOP"
    return "OP"


# ---------------------------------------------------------------------------
# provisional nutritional risk (PRD §3.3)
# ---------------------------------------------------------------------------
def bmi_bonus(bmi):
    b = Decimal(str(bmi))
    if b < Decimal("16"):
        return BMI_SEVERE_BONUS
    if b < Decimal("18.5"):
        return BMI_MODERATE_BONUS
    return Decimal("0")


def provisional_risk(composite, bmi):
    val = Decimal(str(composite)) + bmi_bonus(bmi)
    return _clamp(val, Decimal("0"), Decimal("100"))


# ---------------------------------------------------------------------------
# medical_stability_posture (PRD §3.3)
# ---------------------------------------------------------------------------
def medical_stability_posture(risk_score):
    r = Decimal(str(risk_score))
    if r >= T_UNSTABLE:
        return "UNSTABLE"
    if r >= T_GUARDED:
        return "GUARDED"
    return "STABLE"


# ---------------------------------------------------------------------------
# meal_compliance_rate (PRD §3.6)
# ---------------------------------------------------------------------------
def effective_fraction(completion_fraction, refused):
    if refused:
        return Decimal("0")
    cf = Decimal(str(completion_fraction))
    return _clamp(cf, Decimal("0"), Decimal("1"))


def meal_compliance_rate(completion_points, meals_logged):
    if meals_logged == 0:
        return Decimal("0")
    return _round4(Decimal(str(completion_points)) / Decimal(meals_logged))


# ---------------------------------------------------------------------------
# meal-plan close reconciliation credit (PRD §3.6)
# ---------------------------------------------------------------------------
def meal_close_credit(rate):
    return _round2(MEAL_CREDIT_FACTOR * Decimal(str(rate)))


# ---------------------------------------------------------------------------
# step_down_readiness_score (PRD §3.8)
# ---------------------------------------------------------------------------
def step_down_readiness(goals_met, goals_total, rate, posture):
    if goals_total == 0:
        goal_ratio = Decimal("0")
    else:
        goal_ratio = Decimal(goals_met) / Decimal(goals_total)
    meal_factor = min(Decimal(str(rate)), Decimal("1.0"))
    if posture == "STABLE":
        stability = Decimal("1.0")
    elif posture == "GUARDED":
        stability = Decimal("0.6")
    else:  # UNSTABLE
        stability = Decimal("0.0")
    raw = Decimal("100") * (
        W_GOALS * goal_ratio + W_MEALS * meal_factor + W_STABILITY * stability
    )
    readiness = _round2(raw)
    return _clamp(readiness, Decimal("0"), Decimal("100"))


# ---------------------------------------------------------------------------
# authorized days — whole days in a half-open window (PRD §3.11)
# ---------------------------------------------------------------------------
def whole_days(start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    return int(seconds // SECONDS_PER_DAY)


def days_consumed_chronological(windows, clock_dt):
    """Sum over APPROVED windows of elapsed whole days up to the clock.

    For each window: floor((min(window_end, clock) - window_start) / 86400),
    never less than zero (PRD §3.11).
    """
    total = 0
    for w_start, w_end in windows:
        end = min(w_end, clock_dt)
        seconds = (end - w_start).total_seconds()
        days = int(seconds // SECONDS_PER_DAY)
        if days < 0:
            days = 0
        total += days
    return total


# ---------------------------------------------------------------------------
# patient_responsibility_cents (PRD §3.12)
# ---------------------------------------------------------------------------
def patient_responsibility_cents(daily_rate_cents, coinsurance_pct, days_consumed):
    # Per-day share rounded to whole cents FIRST, then multiplied (order pinned).
    per_day = Decimal(daily_rate_cents) * Decimal(str(coinsurance_pct))
    per_day_share = int(per_day.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return per_day_share * days_consumed
