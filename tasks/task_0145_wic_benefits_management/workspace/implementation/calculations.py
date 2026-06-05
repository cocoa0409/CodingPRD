"""Calculation rules and domain constants (SCAFFOLD §1.3 / PRD §3).

All money is integer cents except the two annualized dollar figures
(annual_income_determined, income_limit), which are dollars rounded to exactly
two decimal places with round-half-up.
"""
import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- Income limit (FPG @ 185%) -------------------------------------------------
WIC_INCOME_PCT = Decimal("1.85")
FPG_ANNUAL = {1: 15060, 2: 20440, 3: 25820, 4: 31200,
              5: 36580, 6: 41960, 7: 47340, 8: 52720}
FPG_INCREMENT = 5380

# --- Income annualization ------------------------------------------------------
FREQ_MULT = {"WEEKLY": 52, "BIWEEKLY": 26, "MONTHLY": 12, "ANNUAL": 1}

# --- Nutritional risk ----------------------------------------------------------
RISK_FACTOR_POINTS = {
    "ANEMIA": 40, "UNDERWEIGHT": 35, "INADEQUATE_DIET": 20,
    "SHORT_STATURE": 15, "ELEVATED_LEAD": 50, "GEST_DIABETES": 45,
}
HIGH_PRIORITY_FACTORS = {"ELEVATED_LEAD", "GEST_DIABETES"}
RISK_THRESHOLD = {"PREGNANT": 30, "POSTPARTUM": 30, "BREASTFEEDING": 30,
                  "INFANT": 25, "CHILD": 35}

# --- Certification length / priority -------------------------------------------
CERT_LENGTH_DAYS = {"PREGNANT": 280, "POSTPARTUM": 180,
                    "BREASTFEEDING": 365, "INFANT": 365, "CHILD": 365}
PRIORITY_BY_CATEGORY = {"PREGNANT": 1, "BREASTFEEDING": 1, "INFANT": 1,
                        "POSTPARTUM": 6, "CHILD": 3}

# --- Food package --------------------------------------------------------------
UNIT_PRICE_CENTS = {
    "MILK": 350, "EGGS": 300, "JUICE": 250, "CEREAL": 400, "FRUIT_VEG": 200,
    "INFANT_FORMULA": 1200, "INFANT_CEREAL": 300,
}
CATEGORY_CAP = {
    "PREGNANT":      {"MILK": 4, "EGGS": 2, "JUICE": 2, "CEREAL": 3, "FRUIT_VEG": 11},
    "POSTPARTUM":    {"MILK": 4, "EGGS": 2, "JUICE": 2, "CEREAL": 3, "FRUIT_VEG": 9},
    "BREASTFEEDING": {"MILK": 6, "EGGS": 2, "JUICE": 2, "CEREAL": 4, "FRUIT_VEG": 11},
    "INFANT":        {"INFANT_FORMULA": 9, "INFANT_CEREAL": 24, "FRUIT_VEG": 8},
    "CHILD":         {"MILK": 4, "EGGS": 1, "JUICE": 2, "CEREAL": 4, "FRUIT_VEG": 8},
}
FOOD_CATEGORIES = set(UNIT_PRICE_CENTS.keys())

# --- Vendor compliance ---------------------------------------------------------
SUSPENSION_THRESHOLD = 100

# --- Peer-session collision ----------------------------------------------------
SESSION_BUFFER_MINUTES = 15


def round_half_up_2(value):
    """Round a Decimal/number to 2 dp, half-up; return a float for JSON."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    """Round to the nearest whole integer, half-up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# income_limit
# =============================================================================
def income_limit(adjusted_size):
    if adjusted_size <= 8:
        base = FPG_ANNUAL[adjusted_size]
    else:
        base = FPG_ANNUAL[8] + (adjusted_size - 8) * FPG_INCREMENT
    return round_half_up_2(Decimal(base) * WIC_INCOME_PCT)


# =============================================================================
# income_determination
# =============================================================================
def _annualize(amount_cents, freq):
    # cents -> dollars (/100) then * periods-per-year
    return (Decimal(amount_cents) / Decimal(100)) * Decimal(FREQ_MULT[freq])


def annual_income_determined(records, income_method):
    """records: list of income-record dicts. Chronological order pinned by
    sequence_index ASC (never id). Returns dollars rounded half-up to 2 dp."""
    most_recent = max(records, key=lambda r: r["sequence_index"])
    freq = most_recent["pay_frequency"]
    if income_method == "AVERAGE_ALL":
        peers = [r for r in records if r["pay_frequency"] == freq]
        total = sum(Decimal(r["gross_amount_cents"]) for r in peers)
        mean = total / Decimal(len(peers))
        avg_cents = round_half_up_int(mean)   # round to whole cents, half-up
        annual = _annualize(avg_cents, freq)
    else:  # ANNUALIZE_RECENT (default)
        annual = _annualize(most_recent["gross_amount_cents"], freq)
    return round_half_up_2(annual)


def income_eligible(annual_income, limit, adjunctive_program):
    if adjunctive_program != "NONE":
        return True
    return Decimal(str(annual_income)) <= Decimal(str(limit))


# =============================================================================
# nutritional_risk_score
# =============================================================================
def nutritional_risk(risk_factor_codes, category):
    total = sum(RISK_FACTOR_POINTS[c] for c in risk_factor_codes)
    high_priority = any(c in HIGH_PRIORITY_FACTORS for c in risk_factor_codes)
    eligible = high_priority or (total >= RISK_THRESHOLD[category])
    return total, eligible


# =============================================================================
# cert_length
# =============================================================================
def cert_period(category, period_start_dt):
    days = CERT_LENGTH_DAYS[category]
    period_end_dt = period_start_dt + timedelta(days=days)
    return days, period_end_dt


# =============================================================================
# prescribed_value (FULL / PRORATED)
# =============================================================================
def issued_units_for_item(requested_units, cap, issuance_mode, current_dt):
    capped = min(requested_units, cap)
    if issuance_mode == "PRORATED":
        days_in_month = calendar.monthrange(current_dt.year, current_dt.month)[1]
        days_remaining = days_in_month - current_dt.day + 1  # inclusive of current day
        factor = Decimal(days_remaining) / Decimal(days_in_month)
        # floor per item BEFORE pricing
        return int(math.floor(Decimal(capped) * factor))
    return capped


def prescribed_value(line_items, category, issuance_mode, current_dt):
    """Returns (prescribed_value_cents, issued_units_by_category dict).

    Raises KeyError-equivalent handling is done by the caller via cap lookup;
    here a missing cap surfaces as the caller checking CATEGORY_CAP membership.
    """
    caps = CATEGORY_CAP[category]
    issued_by_cat = {}
    total = 0
    for item in line_items:
        fc = item["food_category"]
        cap = caps[fc]  # caller has validated fc is in caps
        issued = issued_units_for_item(item["requested_units"], cap,
                                       issuance_mode, current_dt)
        total += issued * UNIT_PRICE_CENTS[fc]
        issued_by_cat[fc] = issued_by_cat.get(fc, 0) + issued
    return total, issued_by_cat
