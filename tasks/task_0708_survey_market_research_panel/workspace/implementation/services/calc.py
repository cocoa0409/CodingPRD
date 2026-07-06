"""Calculation rules (scaffold §1.3, PRD §3.5 / §3.6).

All money and score quantities are integers; fractional intermediates are
rounded HALF-UP to a whole number (PRD §2.9). We use decimal.Decimal with
ROUND_HALF_UP — never float — for the multiplier/weighted/clamp steps.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- incentive_accrual constants (scaffold §1.3 calc 1) ---
LENGTH_BONUS_STEP_MIN = 5
LENGTH_BONUS_POINTS_PER_STEP = 10
CENTS_PER_POINT = 2

# --- quality_score constants (scaffold §1.3 calc 2) ---
W_ATTENTION = Decimal("0.5")
W_SPEED = Decimal("0.3")
W_STRAIGHTLINE = Decimal("0.2")
MIN_SPEED_FRACTION = Decimal("0.34")
MAX_SPEED_FRACTION = Decimal("3.0")
STRAIGHTLINE_PENALTY_PER_RUN = 4
QUALITY_PASS_THRESHOLD = 70
QUALITY_FLAG_THRESHOLD = 50

# --- panel_health_score constants (scaffold §1.3 calc 3) ---
RECENT_WINDOW = 5
INACTIVITY_STEP_DAYS = 30
INACTIVITY_PENALTY_PER_STEP = 5
CHURN_THRESHOLD = 50
CHURN_FLOOR = 30

# --- screening / payout constants ---
MAX_RESCREENS = 3
MIN_PAYOUT_POINTS = 100


def round_half_up(value):
    """Round a numeric value half-up (away from zero on .5) to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_points(base_incentive_points, estimated_minutes):
    """provisional = base + length_bonus, where
    length_bonus = ceil(estimated_minutes / STEP) * POINTS_PER_STEP. (PRD §3.5)
    """
    steps = math.ceil(estimated_minutes / LENGTH_BONUS_STEP_MIN)
    length_bonus = steps * LENGTH_BONUS_POINTS_PER_STEP
    return base_incentive_points + length_bonus


def quality_multiplier(quality_score):
    """1.25 if >=90, 1.00 if >=70, 0.50 if >=50, else 0.00 (PRD §3.5)."""
    if quality_score >= 90:
        return Decimal("1.25")
    if quality_score >= 70:
        return Decimal("1.00")
    if quality_score >= 50:
        return Decimal("0.50")
    return Decimal("0.00")


def finalized_points(provisional, quality_score):
    """round_half_up(provisional * quality_multiplier) (PRD §3.5)."""
    return round_half_up(Decimal(provisional) * quality_multiplier(quality_score))


def quality_score(passed_checks, total_checks, completion_seconds,
                  straightline_run, estimated_minutes):
    """Weighted blend of attention/speed/straightline, half-up to 0-100 (PRD §3.6)."""
    if total_checks > 0:
        attention = (Decimal(passed_checks) / Decimal(total_checks)) * Decimal(100)
    else:
        attention = Decimal(100)

    est_seconds = Decimal(estimated_minutes) * Decimal(60)
    if Decimal(completion_seconds) < est_seconds * MIN_SPEED_FRACTION:
        speed = Decimal(0)
    elif Decimal(completion_seconds) > est_seconds * MAX_SPEED_FRACTION:
        speed = Decimal(50)
    else:
        speed = Decimal(100)

    straightline = max(0, 100 - straightline_run * STRAIGHTLINE_PENALTY_PER_RUN)
    straightline = Decimal(straightline)

    total = (W_ATTENTION * attention
             + W_SPEED * speed
             + W_STRAIGHTLINE * straightline)
    return round_half_up(total)


def quality_status_from_score(score):
    """PASS >=70, FLAGGED >=50 (<70), FAIL <50 (PRD §3.6)."""
    if score >= QUALITY_PASS_THRESHOLD:
        return "PASS"
    if score >= QUALITY_FLAG_THRESHOLD:
        return "FLAGGED"
    return "FAIL"


def health_score(completed_count, invited_count, days_since_activity):
    """base = (completed/invited)*100 (or 100 if denom 0); minus inactivity
    penalty = floor(days/STEP)*PENALTY; clamp 0-100; round half-up (PRD §3.6).
    """
    if invited_count > 0:
        base = (Decimal(completed_count) / Decimal(invited_count)) * Decimal(100)
    else:
        base = Decimal(100)

    if days_since_activity is None:
        penalty = Decimal(0)
    else:
        steps = math.floor(days_since_activity / INACTIVITY_STEP_DAYS)
        penalty = Decimal(steps * INACTIVITY_PENALTY_PER_STEP)

    raw = base - penalty
    clamped = max(Decimal(0), min(Decimal(100), raw))
    return round_half_up(clamped)
