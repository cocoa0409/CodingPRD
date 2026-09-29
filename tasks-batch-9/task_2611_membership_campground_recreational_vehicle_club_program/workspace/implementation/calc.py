"""Constants and every declared calculation (PRD 3.x)."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# --- entitlement / occupancy -------------------------------------------------
ENTITLEMENT_YEAR_DAYS = 365
LINK_GAP_NIGHTS = 1
ABSOLUTE_MAX_RUN_NIGHTS = 45

# --- capacity ----------------------------------------------------------------
TRANSIENT_FLOOR_SITES = 1
SEASON_OPEN_LEAD_DAYS = 30

# --- transient pricing -------------------------------------------------------
CLASS_NIGHT_RATE_CENTS = {"CLASS_A": 8500, "CLASS_B": 6200, "CLASS_C": 4100}
PEAK_START_MMDD = (7, 1)
PEAK_END_MMDD = (9, 7)
PEAK_MULTIPLIER = Decimal("1.35")
WEEKEND_MULTIPLIER = Decimal("1.15")
RESORT_FEE_PCT = Decimal("0.09")

# --- dues --------------------------------------------------------------------
CAPITAL_ASSESSMENT_PCT = Decimal("0.08")
LOYALTY_SUBTOTAL_BAND_CENTS = 60000
LOYALTY_TENURE_YEARS = 5
LOYALTY_PCT_HIGH_LONG = Decimal("0.10")
LOYALTY_PCT_HIGH = Decimal("0.05")
LOYALTY_PCT_LONG = Decimal("0.03")
DUES_NET_DAYS = 30
DUES_CYCLE_DAYS = 365

LATE_FEE_PCT = Decimal("0.015")
DUES_GRACE_START_DAYS = 1
DUES_DELINQUENT_DAYS = 30
DUES_WRITE_OFF_DAYS = 120

# --- surveys / ratings -------------------------------------------------------
W_OVERALL = Decimal("0.40")
W_CLEANLINESS = Decimal("0.25")
W_STAFF = Decimal("0.20")
W_VALUE = Decimal("0.15")
RECENT_DAYS = 90
MID_DAYS = 365
TRAILING_WINDOW_DAYS = 180
DEFAULT_TRAILING_RATING = Decimal("3.00")

# --- amenity inspections -----------------------------------------------------
W_RESTROOM = Decimal("0.35")
W_HOOKUP = Decimal("0.25")
W_UTILITY = Decimal("0.25")
W_ROAD = Decimal("0.15")
AMENITY_PASS_MIN = Decimal("4.00")
AMENITY_PROBATION_MIN = Decimal("3.00")
FORCED_CANCELLATION_PROBATION_THRESHOLD = 2

# --- capital priority --------------------------------------------------------
CATEGORY_WEIGHTS = {
    "SAFETY": Decimal("1.40"),
    "UTILITY": Decimal("1.20"),
    "AMENITY": Decimal("1.00"),
    "EXPANSION": Decimal("0.80"),
}
COMPLIANCE_FACTORS = {
    "NON_COMPLIANT": Decimal("1.30"),
    "PROBATION": Decimal("1.15"),
    "COMPLIANT": Decimal("1.00"),
}
TARGET_RATING = Decimal("4.50")
USAGE_CAP = Decimal("1.50")
USAGE_DENOM_NIGHTS = 30
COST_BAND_LOW_CENTS = 5000000
COST_BAND_MID_CENTS = 20000000

# --- transfers ---------------------------------------------------------------
RESALE_SURCHARGE_PCT = Decimal("0.06")
RESALE_HOLD_DAYS = 730
MAX_TRANSFERS_PER_CHAIN = 2
REINSTATEMENT_FEE_CENTS = 15000

TRANSFER_TYPE_MULTIPLIERS = {
    "RESALE": Decimal("1.00"),
    "GIFT": Decimal("0.50"),
    "ESTATE": Decimal("0.00"),
}

PARK_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
CLASS_BUCKET = {
    "CLASS_A": "nights_used_class_a",
    "CLASS_B": "nights_used_class_b",
    "CLASS_C": "nights_used_class_c",
}
TIER_ENTITLEMENT = {
    "CLASS_A": "entitlement_nights_class_a",
    "CLASS_B": "entitlement_nights_class_b",
    "CLASS_C": "entitlement_nights_class_c",
}


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimals; returns a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def money(value):
    return int(rhu(value, 0))


def score2(value):
    """Two-decimal score as a float for JSON."""
    return float(rhu(value, 2))


# ---------------------------------------------------------------------------
# dues_invoice_total — five pinned steps, two roundings (PRD 3.1)
# ---------------------------------------------------------------------------
def dues_invoice_total(annual_dues_cents, tenure_years):
    base = int(annual_dues_cents)
    capital_assessment = money(dec(base) * CAPITAL_ASSESSMENT_PCT)
    subtotal = base + capital_assessment
    high = subtotal >= LOYALTY_SUBTOTAL_BAND_CENTS
    long_tenure = tenure_years >= LOYALTY_TENURE_YEARS
    if high and long_tenure:
        pct = LOYALTY_PCT_HIGH_LONG
    elif high:
        pct = LOYALTY_PCT_HIGH
    elif long_tenure:
        pct = LOYALTY_PCT_LONG
    else:
        pct = Decimal("0.00")
    loyalty_credit = money(dec(subtotal) * pct)
    amount = subtotal - loyalty_credit
    return {
        "base_dues_cents": base,
        "capital_assessment_cents": capital_assessment,
        "loyalty_credit_cents": loyalty_credit,
        "amount_cents": amount,
    }


# ---------------------------------------------------------------------------
# dues_late_fee — one multiplication, exactly one rounding (PRD 3.7)
# ---------------------------------------------------------------------------
def dues_late_fee(amount_cents, days_past_due):
    if days_past_due <= 0:
        return 0
    months_late = ceil_int(dec(days_past_due) / dec(30))
    return money(dec(amount_cents) * LATE_FEE_PCT * dec(months_late))


# ---------------------------------------------------------------------------
# transient_stay_charge — round per night, then sum (PRD 3.4)
# ---------------------------------------------------------------------------
def _is_peak(d):
    mmdd = (d.month, d.day)
    return PEAK_START_MMDD <= mmdd <= PEAK_END_MMDD


def transient_stay_charge(park_class, arrival, departure):
    base = dec(CLASS_NIGHT_RATE_CENTS[park_class])
    subtotal = 0
    cursor = arrival
    while cursor < departure:
        peak = PEAK_MULTIPLIER if _is_peak(cursor) else Decimal("1.00")
        weekend = WEEKEND_MULTIPLIER if cursor.weekday() in (4, 5) else Decimal("1.00")
        subtotal += money(base * peak * weekend)
        cursor = date.fromordinal(cursor.toordinal() + 1)
    resort_fee = money(dec(subtotal) * RESORT_FEE_PCT)
    return subtotal + resort_fee


# ---------------------------------------------------------------------------
# transfer_fee_total — two independent roundings, integer add (PRD 3.8)
# ---------------------------------------------------------------------------
def transfer_fee_total(tier_transfer_fee_cents, transfer_type, sale_price_cents):
    multiplier = TRANSFER_TYPE_MULTIPLIERS[transfer_type]
    base = money(dec(tier_transfer_fee_cents) * multiplier)
    surcharge = 0
    if transfer_type == "RESALE":
        surcharge = money(dec(sale_price_cents or 0) * RESALE_SURCHARGE_PCT)
    return base + surcharge


# ---------------------------------------------------------------------------
# survey_weighted_score / amenity_composite_score
# ---------------------------------------------------------------------------
def survey_weighted_score(overall, cleanliness, staff, value):
    total = (W_OVERALL * dec(overall) + W_CLEANLINESS * dec(cleanliness)
             + W_STAFF * dec(staff) + W_VALUE * dec(value))
    return rhu(total, 2)


def amenity_composite_score(restroom, hookup, utility, road):
    total = (W_RESTROOM * dec(restroom) + W_HOOKUP * dec(hookup)
             + W_UTILITY * dec(utility) + W_ROAD * dec(road))
    return rhu(total, 2)


def amenity_result(composite):
    if composite >= AMENITY_PASS_MIN:
        return "PASS"
    if composite >= AMENITY_PROBATION_MIN:
        return "PROBATION"
    return "FAIL"


AMENITY_RESULT_STATUS = {
    "PASS": "COMPLIANT",
    "PROBATION": "PROBATION",
    "FAIL": "NON_COMPLIANT",
}


# ---------------------------------------------------------------------------
# park_rating_score — two deliberately disagreeing variants (PRD 3.9)
# ---------------------------------------------------------------------------
def recency_weighted_lifetime(surveys, age_days_of):
    if not surveys:
        return Decimal("0.00")
    weight_total = Decimal("0")
    weighted_total = Decimal("0")
    for survey in surveys:
        age = age_days_of(survey)
        if age <= RECENT_DAYS:
            weight = Decimal("1.0")
        elif age <= MID_DAYS:
            weight = Decimal("0.6")
        else:
            weight = Decimal("0.3")
        weight_total += weight
        weighted_total += weight * dec(survey["weighted_score"])
    if weight_total == 0:
        return Decimal("0.00")
    return rhu(weighted_total / weight_total, 2)


def trailing_window_mean(surveys, age_days_of):
    window = [s for s in surveys if age_days_of(s) <= TRAILING_WINDOW_DAYS]
    if not window:
        return DEFAULT_TRAILING_RATING
    total = sum((dec(s["weighted_score"]) for s in window), Decimal("0"))
    return rhu(total / dec(len(window)), 2)


# ---------------------------------------------------------------------------
# capital_priority_score — five factors, single final rounding (PRD 3.9)
# ---------------------------------------------------------------------------
def capital_priority_score(category, compliance_status, trailing_rating,
                           member_nights_ytd, total_sites, requested_cost_cents):
    compliance_factor = COMPLIANCE_FACTORS.get(compliance_status, Decimal("1.00"))
    category_weight = CATEGORY_WEIGHTS[category]
    satisfaction_gap = TARGET_RATING - dec(trailing_rating)
    if satisfaction_gap < Decimal("0.00"):
        satisfaction_gap = Decimal("0.00")
    denominator = max(1, int(total_sites) * USAGE_DENOM_NIGHTS)
    usage_intensity = rhu(dec(member_nights_ytd) / dec(denominator), 4)
    if usage_intensity > USAGE_CAP:
        usage_intensity = USAGE_CAP
    if requested_cost_cents <= COST_BAND_LOW_CENTS:
        cost_factor = Decimal("1.20")
    elif requested_cost_cents <= COST_BAND_MID_CENTS:
        cost_factor = Decimal("1.00")
    else:
        cost_factor = Decimal("0.85")
    raw = (category_weight * compliance_factor
           * (Decimal("1") + satisfaction_gap)
           * (Decimal("1") + usage_intensity)
           * cost_factor)
    return rhu_int(raw * Decimal("1000"))


def affiliate_quota_nights(nights, reciprocity_ratio):
    return ceil_int(dec(nights) * dec(reciprocity_ratio))
