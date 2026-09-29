"""Deterministic calculations (SCAFFOLD section 1.3 / PRD sections 2.8, 3.x).

Every monetary or score computation runs through decimal.Decimal with
ROUND_HALF_UP.  Never float, never the builtin round().
"""

from decimal import Decimal, ROUND_HALF_UP

D0 = Decimal("0")
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")

# --- review_weighted_score -------------------------------------------------
W_ORIGINALITY = Decimal("0.40")
W_METHODOLOGY = Decimal("0.30")
W_CLARITY = Decimal("0.15")
W_RELEVANCE = Decimal("0.15")
SCORE_FLOOR = Decimal("1.00")
SCORE_CEILING = Decimal("5.50")

# --- abstract_consensus_score ---------------------------------------------
CONFIDENCE_WEIGHT = {"LOW": Decimal("1"), "MEDIUM": Decimal("2"), "HIGH": Decimal("3")}

# --- reviewer_selection_by_expertise --------------------------------------
MIN_MATCH_SCORE = Decimal("0.2500")

# --- cme_credit_award ------------------------------------------------------
CREDIT_STEP = Decimal("0.25")
MINUTES_PER_CREDIT_STEP = 15

# --- program_change_fee ----------------------------------------------------
BASE_FEE_CENTS = {
    "MOVE": 4000,
    "SWAP": 6000,
    "SUBSTITUTE_PRESENTER": 2500,
    "WITHDRAW": 0,
}
RUSH_PCT_ESTIMATE = {"FAR": Decimal("0"), "NEAR": Decimal("10"), "IMMINENT": Decimal("25")}
RUSH_PCT_FINAL = {"FAR": Decimal("0"), "NEAR": Decimal("20"), "IMMINENT": Decimal("50")}
POST_FREEZE_SURCHARGE_CENTS = 1500

# --- session_packing -------------------------------------------------------
CHANGEOVER_MINUTES = 5
SESSION_BUFFER_MINUTES = 10
CHAIR_TURNAROUND_MINUTES = 15


def round2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# review_weighted_score
# ---------------------------------------------------------------------------

def weighted_score(originality, methodology, relevance, clarity, calibration_bias):
    raw = (
        W_ORIGINALITY * Decimal(originality)
        + W_METHODOLOGY * Decimal(methodology)
        + W_CLARITY * Decimal(clarity)
        + W_RELEVANCE * Decimal(relevance)
    )
    biased = raw + dec(calibration_bias)
    value = round2(biased)
    if value < SCORE_FLOOR:
        value = SCORE_FLOOR
    if value > SCORE_CEILING:
        value = SCORE_CEILING
    return value


# ---------------------------------------------------------------------------
# abstract_consensus_score  (dual variant: provisional + final)
# ---------------------------------------------------------------------------

def provisional_score(reviews):
    if not reviews:
        return None
    total = sum((dec(r["weighted_score"]) for r in reviews), D0)
    return round2(total / Decimal(len(reviews)))


def final_score(reviews):
    if not reviews:
        return None
    numerator = D0
    denominator = D0
    for r in reviews:
        weight = CONFIDENCE_WEIGHT.get(r["confidence"], Decimal("1"))
        numerator += weight * dec(r["weighted_score"])
        denominator += weight
    if denominator == 0:
        return None
    return round2(numerator / denominator)


# ---------------------------------------------------------------------------
# abstract_score_spread  (trim-one for three or more reviews)
# ---------------------------------------------------------------------------

def score_spread(reviews):
    values = [dec(r["weighted_score"]) for r in reviews]
    n = len(values)
    if n < 2:
        return None
    if n == 2:
        return round2(abs(values[0] - values[1]))
    best = None
    for index in range(n):
        trimmed = values[:index] + values[index + 1:]
        candidate = max(trimmed) - min(trimmed)
        if best is None or candidate < best:
            best = candidate
    return round2(best)


# ---------------------------------------------------------------------------
# reviewer_selection_by_expertise — Dice coefficient
# ---------------------------------------------------------------------------

def dice_coefficient(left, right):
    a = {str(x).lower() for x in (left or [])}
    b = {str(x).lower() for x in (right or [])}
    if not a and not b:
        return round4(D0)
    return round4(Decimal(2 * len(a & b)) / Decimal(len(a) + len(b)))


# ---------------------------------------------------------------------------
# cme_credit_award
# ---------------------------------------------------------------------------

def credits_for_minutes(minutes):
    if minutes is None or minutes <= 0:
        return Decimal("0.00")
    return (Decimal(int(minutes) // MINUTES_PER_CREDIT_STEP) * CREDIT_STEP).quantize(TWO)


def bundle_credits(minutes_list):
    total = sum(int(m) for m in minutes_list) if minutes_list else 0
    return credits_for_minutes(total)


# ---------------------------------------------------------------------------
# program_change_fee
# ---------------------------------------------------------------------------

def urgency_band(days_to_event):
    if days_to_event >= 14:
        return "FAR"
    if days_to_event >= 7:
        return "NEAR"
    return "IMMINENT"


def estimated_fee(change_type, days_to_event):
    base = Decimal(BASE_FEE_CENTS[change_type])
    pct = RUSH_PCT_ESTIMATE[urgency_band(days_to_event)]
    return round_cents(base * (Decimal("1") + pct / Decimal("100")))


def final_fee(change_type, days_to_event, post_freeze):
    base = Decimal(BASE_FEE_CENTS[change_type])
    pct = RUSH_PCT_FINAL[urgency_band(days_to_event)]
    total = round_cents(base * (Decimal("1") + pct / Decimal("100")))
    if post_freeze:
        total += POST_FREEZE_SURCHARGE_CENTS
    return total


def rush_pct_final(days_to_event):
    return RUSH_PCT_FINAL[urgency_band(days_to_event)]


# ---------------------------------------------------------------------------
# session_packing
# ---------------------------------------------------------------------------

def committed_minutes(durations):
    n = len(durations)
    if n == 0:
        return 0
    return sum(durations) + CHANGEOVER_MINUTES * max(0, n - 1)


def packing_admissible(durations, new_duration, window_minutes):
    n = len(durations)
    required = (
        SESSION_BUFFER_MINUTES
        + sum(durations)
        + new_duration
        + CHANGEOVER_MINUTES * max(0, n)
    )
    return required <= window_minutes
