"""Pure calculation functions. Integer cents, round-half-up where specified."""
from decimal import Decimal, ROUND_HALF_UP

# constants
RISK_SURCHARGE_BPS = 2500
MIN_RESIDUAL_FLOOR_CENTS = 5000
DAYS_PER_MONTH = 30
VELOCITY_WINDOW_DAYS = 90
REVIEW_THRESHOLD = 2
BLOCK_THRESHOLD = 3
GRADE_BPS = {"A": 6000, "B": 4000, "C": 2000, "EWASTE": 0}
NONRETURN_FEE_BPS = 3500
RETURN_WINDOW_DAYS = 30


def round_half_up(value):
    """Round a numeric/Decimal to an integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote_deductible(peril, plan, risk_flag):
    # STEP 1 tier base
    if peril == "CRACKED":
        tier_base = plan["base_deductible_cents"]
    else:  # LOST or THEFT
        tier_base = round_half_up(
            Decimal(plan["base_deductible_cents"])
            * Decimal(plan["loss_deductible_multiplier_bps"]) / Decimal(10000)
        )
    # STEP 2 risk surcharge
    if risk_flag == "WATCH":
        surcharge = round_half_up(Decimal(tier_base) * Decimal(RISK_SURCHARGE_BPS) / Decimal(10000))
    else:  # GREEN (BLOCKED never reaches approval)
        surcharge = 0
    return tier_base + surcharge


def age_months(device_purchase_date, current_clock):
    days = (current_clock - device_purchase_date).total_seconds() / 86400.0
    import math
    return int(math.floor(days / DAYS_PER_MONTH))


def depreciated_value(sku, device_purchase_date, current_clock):
    """The greater of raw depreciated figure and the floor (pre-cap)."""
    months = age_months(device_purchase_date, current_clock)
    if months < 0:
        months = 0
    dep_amount = round_half_up(
        Decimal(sku["msrp_cents"]) * Decimal(sku["depreciation_rate_bps_per_month"])
        * Decimal(months) / Decimal(10000)
    )
    raw = sku["msrp_cents"] - dep_amount
    return max(raw, MIN_RESIDUAL_FLOOR_CENTS)


def replacement_value(sku, plan, device_purchase_date, current_clock):
    dep = depreciated_value(sku, device_purchase_date, current_clock)
    return min(dep, plan["replacement_value_cap_cents"])


def net_payout(replacement_value_cents, deductible_cents):
    return max(replacement_value_cents - deductible_cents, 0)


def fraud_outcome(velocity_count):
    if velocity_count >= BLOCK_THRESHOLD:
        return "BLOCK"
    if velocity_count >= REVIEW_THRESHOLD:
        return "REVIEW"
    return "PASS"


def tradein_credit(base, condition_grade):
    factor_bps = GRADE_BPS.get(condition_grade, 0)
    return round_half_up(Decimal(base) * Decimal(factor_bps) / Decimal(10000))


def nonreturn_fee(sku):
    return round_half_up(Decimal(sku["msrp_cents"]) * Decimal(NONRETURN_FEE_BPS) / Decimal(10000))


def luhn_valid(imei):
    if not isinstance(imei, str) or len(imei) != 15 or not imei.isdigit():
        return False
    total = 0
    # Luhn: double every second digit from the right
    for i, ch in enumerate(reversed(imei)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
