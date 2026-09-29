"""Pure numeric rules — rounding, handicaps, prizes, fees (PRD sections 2.5, 3.3, 3.8, 3.9).

Every monetary and handicap quantity is computed with decimal.Decimal and
ROUND_HALF_UP.  No float arithmetic is used for anything that is rounded.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- handicap rules (PRD 3.3) ---
SLOPE_BASE = Decimal("113")
MAX_COURSE_HANDICAP = 36
MIN_COURSE_HANDICAP = 0
MAX_INDEX_IMPROVEMENT = Decimal("3.0")
MIN_HANDICAP_INDEX = Decimal("0")
MAX_HANDICAP_INDEX = Decimal("54.0")
SCRAMBLE_WEIGHTS = (Decimal("0.20"), Decimal("0.15"), Decimal("0.10"), Decimal("0.05"))
BEST_BALL_ALLOWANCE_PCT = Decimal("0.90")
STROKE_PLAY_ALLOWANCE_PCT = Decimal("1.00")
TEAM_AGGREGATE_MULTIPLIER = Decimal("0.25")

# --- prize rules (PRD 3.8) ---
PRIZE_SHARES = (Decimal("0.50"), Decimal("0.30"))
AMATEUR_CASH_CAP_CENTS = 75000

# --- contest insurance (PRD 3.6) ---
INSURANCE_REQUIRED_THRESHOLD_CENTS = 500000
DEFAULT_INSURANCE_MIN_YARDAGE = 165
DEFAULT_INSURANCE_WITNESS_COUNT = 2

# --- fiscal rules (PRD 3.2, 3.4, 3.7, 3.9) ---
LATE_CANCEL_FEE_PCT = Decimal("0.25")
WAIVER_CREDIT_PCT = Decimal("0.60")
TOKEN_GSV_CAP_CENTS = 1300
TOKEN_GSV_PCT = Decimal("0.02")
ADMIN_FEE_TIER_1_LIMIT_CENTS = 2000000
ADMIN_FEE_TIER_2_LIMIT_CENTS = 5000000
ADMIN_FEE_PCT_TIER_1 = 0.05
ADMIN_FEE_PCT_TIER_2 = 0.035
ADMIN_FEE_PCT_TIER_3 = 0.02

# --- operational limits (PRD 3.1, 3.5) ---
MAX_FIELD_REOPENS = 2
CHANGEOVER_BUFFER_MINUTES = 30
CART_TURNAROUND_MINUTES = 30
CART_PREP_MINUTES = 15
PLAYER_SLOTS_PER_TEAM = 4


def dec(value):
    """Decimal from any numeric input without going through binary float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to whole cents and return a plain int."""
    return int(round_half_up(value, 0))


def strokes(value):
    """Round half up to a whole stroke and return a plain int."""
    return int(round_half_up(value, 0))


def one_dp(value):
    return float(round_half_up(value, 1))


def two_dp(value):
    return float(round_half_up(value, 2))


def pct_of(pct, amount):
    """Whole-cent result of a percentage applied to a cent amount."""
    return cents(dec(pct) * dec(amount))


# --------------------------------------------------------------------------
# Course handicap conversion (PRD 3.3)
# --------------------------------------------------------------------------
def course_handicap(index, slope_rating, course_rating, par):
    raw = dec(index) * dec(slope_rating) / SLOPE_BASE + dec(course_rating) - dec(par)
    whole = strokes(raw)
    if whole < MIN_COURSE_HANDICAP:
        whole = MIN_COURSE_HANDICAP
    if whole > MAX_COURSE_HANDICAP:
        whole = MAX_COURSE_HANDICAP
    return whole


def sandbag_capped_index(current_index, index_at_confirm):
    """The larger of the current index and the confirmation snapshot less 3.0."""
    if index_at_confirm is None:
        return None if current_index is None else float(dec(current_index))
    floor_value = dec(index_at_confirm) - MAX_INDEX_IMPROVEMENT
    if current_index is None:
        return float(floor_value)
    current = dec(current_index)
    return float(current if current > floor_value else floor_value)


# --------------------------------------------------------------------------
# Team playing handicap (PRD 3.3)
# --------------------------------------------------------------------------
def team_playing_handicap(sorted_course_handicaps, fmt):
    values = [dec(v) for v in sorted_course_handicaps if v is not None]
    if not values:
        return 0.0
    if fmt == "SCRAMBLE":
        total = Decimal("0")
        for i, value in enumerate(values):
            if i >= len(SCRAMBLE_WEIGHTS):
                break
            total += value * SCRAMBLE_WEIGHTS[i]
        return one_dp(total)
    pct = BEST_BALL_ALLOWANCE_PCT if fmt == "BEST_BALL" else STROKE_PLAY_ALLOWANCE_PCT
    total = 0
    for value in values:
        total += strokes(value * pct)
    return one_dp(dec(total) * TEAM_AGGREGATE_MULTIPLIER)


# --------------------------------------------------------------------------
# Net scoring metrics (PRD 3.8)
# --------------------------------------------------------------------------
def net_metrics(team_handicap, gross_score, gross_back_9, gross_back_6,
                gross_back_3, gross_hole_18):
    tph = dec(team_handicap or 0)
    return {
        "net_score": one_dp(dec(gross_score) - tph),
        "net_back_9": two_dp(dec(gross_back_9) - tph / dec(2)),
        "net_back_6": two_dp(dec(gross_back_6) - tph / dec(3)),
        "net_back_3": two_dp(dec(gross_back_3) - tph / dec(6)),
        "net_hole_18": two_dp(dec(gross_hole_18) - tph / dec(18)),
    }


# --------------------------------------------------------------------------
# Prize distribution (PRD 3.8)
# --------------------------------------------------------------------------
def prize_awards(prize_pool_cents, eligible_count):
    """Ordered awards for the eligible teams, in rank order."""
    awards = []
    if eligible_count <= 0 or prize_pool_cents <= 0:
        return [0] * max(eligible_count, 0)
    for i in range(eligible_count):
        if i < len(PRIZE_SHARES):
            awards.append(pct_of(PRIZE_SHARES[i], prize_pool_cents))
        elif i == len(PRIZE_SHARES):
            awards.append(prize_pool_cents - sum(awards))
        else:
            awards.append(0)
    return awards


# --------------------------------------------------------------------------
# Administrative fee (PRD 3.9 step 7)
# --------------------------------------------------------------------------
def admin_fee_pct(net_before_fee_cents):
    if net_before_fee_cents <= 0:
        return 0
    if net_before_fee_cents < ADMIN_FEE_TIER_1_LIMIT_CENTS:
        return ADMIN_FEE_PCT_TIER_1
    if net_before_fee_cents < ADMIN_FEE_TIER_2_LIMIT_CENTS:
        return ADMIN_FEE_PCT_TIER_2
    return ADMIN_FEE_PCT_TIER_3


# --------------------------------------------------------------------------
# Charitable deduction (PRD 3.7)
# --------------------------------------------------------------------------
def token_benefit_ceiling(payment_cents):
    two_percent = cents(TOKEN_GSV_PCT * dec(payment_cents))
    return min(TOKEN_GSV_CAP_CENTS, two_percent)


def registration_deduction(payment_cents, declared_gsv_cents):
    ceiling = token_benefit_ceiling(payment_cents)
    gsv = 0 if declared_gsv_cents <= ceiling else declared_gsv_cents
    return gsv, max(0, payment_cents - gsv)
