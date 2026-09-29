"""Every declared calculation, with round-half-up discipline (PRD 2.7, 3.x)."""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal(1)
TWO_PLACES = Decimal("0.01")

# ------------------------------------------------------------------ constants
WEIGHT_TONE = Decimal("1.2")
WEIGHT_RHYTHM = Decimal("1.0")
WEIGHT_INTONATION = Decimal("1.0")
WEIGHT_SIGHT_READING = Decimal("0.8")

TRIM_MIN_SCORE_COUNT = 4

TIER_BAND_SYMPHONY = Decimal("85.00")
TIER_BAND_PHILHARMONIC = Decimal("75.00")
TIER_BAND_CONCERT = Decimal("62.50")

TIER_MULTIPLIER = {
    "SYMPHONY": Decimal("1.25"),
    "PHILHARMONIC": Decimal("1.00"),
    "CONCERT_ORCHESTRA": Decimal("0.80"),
}
SIBLING_DISCOUNT_PCT = Decimal("0.10")
LOYALTY_CREDIT_PCT_PER_YEAR = Decimal("0.015")
LOYALTY_MAX_YEARS = 4
LOAN_FEE = {"STRING": 4500, "WIND": 6500, "PERCUSSION": 9000}

AID_CAP_PCT = {
    "BAND_A": Decimal("0.60"),
    "BAND_B": Decimal("0.40"),
    "BAND_C": Decimal("0.25"),
}
BAND_POINTS = {"BAND_A": 40, "BAND_B": 25, "BAND_C": 10}
TIER_POINTS = {"SYMPHONY": 5, "PHILHARMONIC": 3, "CONCERT_ORCHESTRA": 1}
AID_NEED_SIBLING_POINTS = 8
AID_NEED_SENIORITY_PER_YEAR = 3
AID_NEED_SENIORITY_MAX_YEARS = 5
AID_NEED_LOAN_POINTS = 6

PER_MEMBER_AID_SHARE = Decimal("0.30")
MIN_AWARD_CENTS = 5000

TARDY_TO_ABSENCE_RATIO = 3
UNEXCUSED_PROBATION_THRESHOLD = 3

ATTENDANCE_WEIGHT = {
    "PRESENT": Decimal("1.0"),
    "TARDY": Decimal("0.5"),
    "EXCUSED_ABSENT": Decimal("0.75"),
    "ABSENCE_UNVERIFIED": Decimal("0.0"),
    "EXCUSE_PENDING": Decimal("0.0"),
    "UNEXCUSED_ABSENT": Decimal("0.0"),
}
ATTENDANCE_ELIGIBILITY_THRESHOLD = Decimal("80.00")

ROOM_TURNOVER_BUFFER_MINUTES = 15
EXCUSE_REQUEST_WINDOW_HOURS = 48
OFFER_TTL_HOURS = 72
MAX_REVISION_ROUNDS = 2
GUEST_ARTIST_FEE_CAP_CENTS = 500000

INSTRUMENTS = (
    "VIOLIN", "VIOLA", "CELLO", "BASS", "FLUTE", "OBOE", "CLARINET",
    "BASSOON", "HORN", "TRUMPET", "TROMBONE", "PERCUSSION",
)
STRING_INSTRUMENTS = ("VIOLIN", "VIOLA", "CELLO", "BASS")

TIER_ORDER = {"CONCERT_ORCHESTRA": 1, "PHILHARMONIC": 2, "SYMPHONY": 3}


# ------------------------------------------------------------------ rounding
def rhu2(value):
    """Round half up to exactly two decimal places."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to a whole number of cents."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------- audition math
def instrument_class(instrument):
    if instrument in STRING_INSTRUMENTS:
        return "STRING"
    if instrument == "PERCUSSION":
        return "PERCUSSION"
    return "WIND"


def weighted_total(tone, rhythm, intonation, sight_reading):
    exact = (Decimal(tone) * WEIGHT_TONE
             + Decimal(rhythm) * WEIGHT_RHYTHM
             + Decimal(intonation) * WEIGHT_INTONATION
             + Decimal(sight_reading) * WEIGHT_SIGHT_READING)
    return rhu2(exact)


def mean2(values):
    total = Decimal(0)
    for value in values:
        total += Decimal(value)
    return rhu2(total / Decimal(len(values)))


def provisional_composite(sheets):
    """Plain mean over every sheet of the current round, no trimming."""
    return mean2([s["weighted_total"] for s in sheets])


def final_composite(sheets):
    """Conditional symmetric trim (one max, one min) when 4+ sheets, then mean.

    Ties on an extreme value are broken by the earliest created_at; the row id
    is never a tie-break.  ``sheets`` must already be in created_at order.
    """
    rows = list(sheets)
    if len(rows) >= TRIM_MIN_SCORE_COUNT:
        highest = max(r["weighted_total"] for r in rows)
        lowest = min(r["weighted_total"] for r in rows)
        drop_high = next(r for r in rows if r["weighted_total"] == highest)
        remaining = [r for r in rows if r is not drop_high]
        drop_low = next(r for r in remaining if r["weighted_total"] == lowest)
        rows = [r for r in remaining if r is not drop_low]
    return mean2([r["weighted_total"] for r in rows])


def tier_recommendation(composite):
    if composite >= TIER_BAND_SYMPHONY:
        return "SYMPHONY"
    if composite >= TIER_BAND_PHILHARMONIC:
        return "PHILHARMONIC"
    if composite >= TIER_BAND_CONCERT:
        return "CONCERT_ORCHESTRA"
    return "NOT_PLACED"


# ---------------------------------------------------------------- tuition math
def gross_cents(tuition_base_cents, tier):
    return rhu_cents(Decimal(tuition_base_cents) * TIER_MULTIPLIER[tier])


def sibling_discount(gross, sibling_enrolled):
    if not sibling_enrolled:
        return 0
    return rhu_cents(Decimal(gross) * SIBLING_DISCOUNT_PCT)


def loyalty_credit(gross, years_in_org):
    years = min(int(years_in_org or 0), LOYALTY_MAX_YEARS)
    if years < 1:
        return 0
    return rhu_cents(Decimal(gross) * LOYALTY_CREDIT_PCT_PER_YEAR * Decimal(years))


def loan_fee(instrument_class_loaned):
    if not instrument_class_loaned:
        return 0
    return LOAN_FEE[instrument_class_loaned]


def aid_cap(assessed_cents, income_band):
    return rhu_cents(Decimal(assessed_cents) * AID_CAP_PCT[income_band])


def aid_need_score(income_band, sibling_enrolled, years_in_org, loan_requested, tier):
    score = BAND_POINTS[income_band]
    if sibling_enrolled:
        score += AID_NEED_SIBLING_POINTS
    score += AID_NEED_SENIORITY_PER_YEAR * min(int(years_in_org or 0),
                                               AID_NEED_SENIORITY_MAX_YEARS)
    if loan_requested:
        score += AID_NEED_LOAN_POINTS
    score += TIER_POINTS[tier]
    return score


def per_member_ceiling(aid_budget_cents):
    return rhu_cents(Decimal(aid_budget_cents) * PER_MEMBER_AID_SHARE)


# ------------------------------------------------------------- attendance math
def effective_unexcused(unexcused_count, tardy_count):
    return unexcused_count + (tardy_count // TARDY_TO_ABSENCE_RATIO)


def attendance_index(statuses):
    if not statuses:
        return rhu2(0)
    total = Decimal(0)
    for status in statuses:
        total += ATTENDANCE_WEIGHT[status]
    return rhu2(Decimal(100) * total / Decimal(len(statuses)))
