"""All calculation rules from PRD section 3, using Decimal with round-half-up."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

# ---- helpers ---------------------------------------------------------------

def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    """Round half up to whole cents, returning an int."""
    return int(rhu(value, 0))


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


# ---- inquiry_priority_score ------------------------------------------------
ACUITY_BY_CARE_LEVEL = {
    "INDEPENDENT_LIVING": 22, "ASSISTED_LIVING": 57,
    "MEMORY_CARE": 86, "SKILLED_NURSING": 100,
}
URGENCY_HORIZON_DAYS = 90
BUDGET_REFERENCE_CENTS = 600000
W_ACUITY = Decimal("0.45")
W_URGENCY = Decimal("0.35")
W_BUDGET = Decimal("0.20")


def inquiry_priority_score(care_level, days_to_move, budget_cents):
    acuity_norm = Decimal(ACUITY_BY_CARE_LEVEL[care_level])
    days = min(days_to_move, URGENCY_HORIZON_DAYS)
    urgency_norm = rhu(Decimal(100) * (URGENCY_HORIZON_DAYS - days) / URGENCY_HORIZON_DAYS, 2)
    budget_norm = min(Decimal("100.00"),
                      rhu(Decimal(100) * Decimal(budget_cents) / BUDGET_REFERENCE_CENTS, 2))
    return (rhu(W_ACUITY * acuity_norm, 2)
            + rhu(W_URGENCY * urgency_norm, 2)
            + rhu(W_BUDGET * budget_norm, 2))


# ---- recommended_care_level ------------------------------------------------

def recommended_care_level(adl, cognitive, mobility):
    total = adl + cognitive + mobility
    if total >= 25:
        return "SKILLED_NURSING"
    if cognitive >= 8:
        return "MEMORY_CARE"
    if total <= 8:
        return "INDEPENDENT_LIVING"
    if total <= 17:
        return "ASSISTED_LIVING"
    return "MEMORY_CARE"


# ---- affordability_ceiling -------------------------------------------------
BUDGET_STRETCH_FACTOR = Decimal("1.10")


def affordability_ceiling(budget_monthly_cents, benefit_offset_cents):
    stretched = money(Decimal(budget_monthly_cents) * BUDGET_STRETCH_FACTOR)
    return stretched + benefit_offset_cents


# ---- match_fit_score -------------------------------------------------------
CARE_ORDER = {"INDEPENDENT_LIVING": 1, "ASSISTED_LIVING": 2,
              "MEMORY_CARE": 3, "SKILLED_NURSING": 4}
BUDGET_COMFORT_RATIO = Decimal("0.85")
BUDGET_FALLOFF_SLOPE = Decimal("300")
W_CARE = Decimal("0.40")
W_BUDGET_FIT = Decimal("0.35")
W_QUALITY = Decimal("0.15")
W_AVAILABILITY = Decimal("0.10")


def match_fit_score(match_care_level, rec, ceiling, rate, quality_rating, available_units):
    if match_care_level == rec:
        care_fit = Decimal(100)
    elif CARE_ORDER[match_care_level] == CARE_ORDER[rec] + 1:
        care_fit = Decimal(60)
    else:
        care_fit = Decimal(0)

    ratio = Decimal(rate) / Decimal(ceiling)
    if ratio > Decimal("1.0"):
        budget_fit = Decimal("0.00")
    elif ratio <= BUDGET_COMFORT_RATIO:
        budget_fit = Decimal("100.00")
    else:
        budget_fit = rhu(max(Decimal("0.0"),
                             Decimal(100) - BUDGET_FALLOFF_SLOPE * (ratio - BUDGET_COMFORT_RATIO)), 2)

    quality_fit = rhu(Decimal(20) * D(quality_rating), 2)
    availability_fit = min(Decimal("100.00"), Decimal(20) * Decimal(available_units))

    total = (W_CARE * care_fit + W_BUDGET_FIT * budget_fit
             + W_QUALITY * quality_fit + W_AVAILABILITY * availability_fit)
    return rhu(total, 2)


# ---- referral_fee ----------------------------------------------------------
CARE_PREMIUM_PCT = {"INDEPENDENT_LIVING": Decimal("0.00"), "ASSISTED_LIVING": Decimal("0.05"),
                    "MEMORY_CARE": Decimal("0.12"), "SKILLED_NURSING": Decimal("0.15")}
TIER_MULTIPLIER = {"STANDARD": Decimal("1.00"), "PREFERRED": Decimal("1.10"), "PREMIER": Decimal("1.25")}
MIN_FEE_CENTS = 150000
MAX_FEE_CENTS = 900000
PRORATION_BASIS_DAYS = 30


def proration_ratio(actual_move_in_date):
    """actual_move_in_date is a datetime.date."""
    occupied_days = min(PRORATION_BASIS_DAYS, 31 - actual_move_in_date.day)
    return Decimal(occupied_days) / Decimal(PRORATION_BASIS_DAYS)


def referral_fee(rate, referral_fee_pct, ratio, care_level, contract_tier):
    rate = Decimal(rate)
    ratio = D(ratio)
    base_cents = money(rate * D(referral_fee_pct) * ratio)
    care_premium_cents = money(rate * CARE_PREMIUM_PCT[care_level] * ratio)
    tier_bonus_cents = money(Decimal(base_cents) * (TIER_MULTIPLIER[contract_tier] - Decimal("1.00")))
    raw = base_cents + care_premium_cents + tier_bonus_cents
    return min(MAX_FEE_CENTS, max(MIN_FEE_CENTS, raw))


# ---- va_benefit_estimate ---------------------------------------------------
UME_INCOME_THRESHOLD_PCT = Decimal("0.05")
VA_MAX_MONTHLY_CENTS = {
    "VA_AID_ATTENDANCE_MARRIED": 276000,
    "VA_AID_ATTENDANCE_SINGLE": 233000,
    "VA_SURVIVOR_PENSION": 149800,
    "LTC_INSURANCE": 200000,
    "BRIDGE_LOAN": 120000,
}


def va_benefit_key(benefit_type, marital_status):
    if benefit_type == "VA_AID_ATTENDANCE":
        if marital_status == "MARRIED":
            return "VA_AID_ATTENDANCE_MARRIED"
        return "VA_AID_ATTENDANCE_SINGLE"
    return benefit_type


def va_benefit_estimate(budget_monthly_cents, gross_monthly_income_cents, marital_status, benefit_type):
    projected = budget_monthly_cents
    ume = max(0, projected - money(UME_INCOME_THRESHOLD_PCT * Decimal(gross_monthly_income_cents)))
    countable = max(0, gross_monthly_income_cents - ume)
    cap = VA_MAX_MONTHLY_CENTS[va_benefit_key(benefit_type, marital_status)]
    benefit = max(0, min(cap, cap - countable))
    return ume, countable, benefit


# ---- clawback_amount -------------------------------------------------------
CLAWBACK_FULL_DAYS = 30
CLAWBACK_PARTIAL_DAYS = 90


def clawback_amount(final_fee_cents, days_resided, has_recognized_invoice):
    if not has_recognized_invoice:
        return 0
    if days_resided <= CLAWBACK_FULL_DAYS:
        pct = Decimal("1.00")
    elif days_resided <= CLAWBACK_PARTIAL_DAYS:
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.00")
    return money(Decimal(final_fee_cents) * pct)


# ---- satisfaction_composite_score ------------------------------------------
W_NPS = Decimal("0.40")
W_CARE_S = Decimal("0.35")
W_VALUE = Decimal("0.25")


def satisfaction_composite(nps, care, value):
    nps_norm = Decimal(10 * nps)
    care_norm = Decimal(20 * care)
    value_norm = Decimal(20 * value)
    return rhu(W_NPS * nps_norm + W_CARE_S * care_norm + W_VALUE * value_norm, 2)


# ---- advisor load indices --------------------------------------------------
PRIORITY_SCORE_MAX = 100


def headcount_index(active_count, capacity):
    return rhu(Decimal(active_count) / Decimal(capacity), 4)


def weighted_index(sum_priority, capacity):
    return rhu(D(sum_priority) / (Decimal(capacity) * Decimal(PRIORITY_SCORE_MAX)), 4)
