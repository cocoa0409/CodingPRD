"""Money, date and interval arithmetic (PRD 2.9, 2.12 and 3.7)."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

DAYS_PER_AGE_YEAR = 365
MILEAGE_BLOCK_MILES = 10000
CLAIM_WEIGHT = Decimal("0.60")
AUDIT_WEIGHT = Decimal("0.40")


def dec(value):
    return Decimal(str(value))


def floor_mul(amount, fraction):
    """floor(amount * fraction) in whole cents."""
    return int((dec(amount) * dec(fraction)).to_integral_value(rounding=ROUND_FLOOR))


def half_up_mul(amount, fraction):
    return int((dec(amount) * dec(fraction)).to_integral_value(rounding=ROUND_HALF_UP))


def ratio_2dp(numerator, denominator):
    """Round half up to exactly 2 decimals, substituting 1 for a zero denominator."""
    den = denominator if denominator else 1
    quotient = dec(numerator) / dec(den)
    return float(quotient.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ceil_mul(fraction, count):
    return int((dec(fraction) * dec(count)).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- #
# calendar arithmetic
# --------------------------------------------------------------------------- #
def add_months(anchor, months):
    """Calendar-month addition clamped to the last day of the target month."""
    total = (anchor.year * 12 + (anchor.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_years(anchor, years):
    return add_months(anchor, 12 * years)


def whole_days(start, end):
    return (end - start).days


# --------------------------------------------------------------------------- #
# certification fee (PRD 3.7)
# --------------------------------------------------------------------------- #
def certification_fee(config, in_service_date, activation_date, odometer, lifetime_activated):
    age_days = whole_days(in_service_date, activation_date)
    age_years = age_days // DAYS_PER_AGE_YEAR
    age_over = max(0, age_years - config["age_surcharge_free_years"])
    miles_over = max(0, odometer - config["mileage_surcharge_free_miles"])
    blocks = miles_over // MILEAGE_BLOCK_MILES
    raw_surcharge = (
        age_over * config["age_surcharge_cents_per_year"]
        + blocks * config["mileage_surcharge_cents_per_10k"]
    )
    surcharge_cap = floor_mul(config["base_fee_cents"], config["surcharge_cap_pct"])
    fee_surcharge_cents = min(raw_surcharge, surcharge_cap)
    subtotal = config["base_fee_cents"] + fee_surcharge_cents

    pct = 0.0
    best_min = None
    for tier in config["volume_discount_tiers"] or []:
        min_count = tier.get("min_count")
        if min_count is None:
            continue
        if min_count <= lifetime_activated and (best_min is None or min_count > best_min):
            best_min = min_count
            pct = tier.get("pct") or 0.0
    fee_discount_cents = floor_mul(subtotal, pct)
    fee_charged_cents = subtotal - fee_discount_cents
    return fee_surcharge_cents, fee_discount_cents, fee_charged_cents


# --------------------------------------------------------------------------- #
# warranty coverage (PRD 3.7)
# --------------------------------------------------------------------------- #
def warranty_coverage(config, in_service_date, activation_date, odometer):
    factory_expiry = add_months(in_service_date, config["factory_basic_months"])
    factory_active = (
        activation_date < factory_expiry and odometer < config["factory_basic_miles"]
    )
    if factory_active:
        start = factory_expiry
        variant = "IN_SERVICE_ANCHORED"
    else:
        start = activation_date
        variant = "CERTIFICATION_ANCHORED"

    raw_end = add_months(start, config["warranty_extension_months"])
    cap_end = add_months(in_service_date, config["warranty_total_cap_months"])
    end = min(raw_end, cap_end)

    raw_end_miles = odometer + config["warranty_extension_miles"]
    end_miles = min(raw_end_miles, config["warranty_total_cap_miles"])

    retention = add_years(end, config["doc_retention_years"])
    return variant, start, end, end_miles, retention


def coverage_conflicts(candidate_start, candidate_end, retained_start, retained_end):
    """Half-open intervals; adjacency is allowed."""
    if not (candidate_start and candidate_end and retained_start and retained_end):
        return False
    return candidate_start < retained_end and retained_start < candidate_end


# --------------------------------------------------------------------------- #
# technician slots (PRD 2.12 / 3.3)
# --------------------------------------------------------------------------- #
def buffered_slot(started_at, slot_minutes, buffer_minutes):
    low = started_at - timedelta(minutes=buffer_minutes)
    high = started_at + timedelta(minutes=slot_minutes + buffer_minutes)
    return low, high


def slot_conflicts(candidate, occupied):
    """Closed buffered intervals; adjacency is forbidden."""
    return candidate[0] <= occupied[1] and occupied[0] <= candidate[1]


# --------------------------------------------------------------------------- #
# dealer behaviour (PRD 3.9)
# --------------------------------------------------------------------------- #
def risk_score(claim_ratio_effective, audit_fail_rate):
    weighted = (
        dec(claim_ratio_effective) * Decimal("100") * CLAIM_WEIGHT
        + dec(audit_fail_rate) * Decimal("100") * AUDIT_WEIGHT
    )
    value = int(weighted.to_integral_value(rounding=ROUND_HALF_UP))
    return min(100, value)


def window_bounds(config, today):
    """Inclusive [today - claim_window_days, today]."""
    return today - timedelta(days=config["claim_window_days"]), today
