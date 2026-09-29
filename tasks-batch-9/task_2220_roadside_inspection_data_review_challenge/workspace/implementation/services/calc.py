"""Numeric primitives, tier tables and the constants of SCAFFOLD 1.3."""

from decimal import Decimal, ROUND_HALF_UP

CATEGORIES = (
    "UNSAFE_DRIVING",
    "HOURS_OF_SERVICE",
    "VEHICLE_MAINTENANCE",
    "DRIVER_FITNESS",
)

CATEGORY_WEIGHT = {
    "UNSAFE_DRIVING": Decimal("0.35"),
    "HOURS_OF_SERVICE": Decimal("0.30"),
    "VEHICLE_MAINTENANCE": Decimal("0.25"),
    "DRIVER_FITNESS": Decimal("0.10"),
}

SEGMENTS = ("SMALL", "MEDIUM", "LARGE")

LOOKBACK_DAYS = 730
CHALLENGE_FILING_WINDOW_DAYS = 730
QUOTA_WINDOW_DAYS = 30
MAX_INFO_ROUNDS = 3
INFO_RESPONSE_DAYS = 30
COACHING_TRIGGER = Decimal("12.0")
COACHING_DUE_DAYS = 14
COACHING_ESCALATION_DAYS = 30
DUPLICATE_BUFFER_MINUTES = 120
OOS_ADDER_PER_VIOLATION = Decimal("0.5")
OOS_ADDER_CAP = Decimal("10.0")
BAND_INSPECT_MIN = Decimal("75.0")
BAND_OPTIONAL_MIN = Decimal("50.0")
INVESTIGATION_ALERT_COUNT = 2
ACTIVE_STATUSES = ("ACTIVE", "RECODED")
SECONDS_PER_DAY = 86400


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to a fixed number of decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and return a JSON number."""
    return float(rhu(value, places))


def whole_days(later, earlier):
    """Whole days between two aware datetimes, fractional part discarded."""
    delta = (later - earlier).total_seconds()
    return int(delta // SECONDS_PER_DAY)


def time_weight_for_age(age_days):
    if age_days <= 182:
        return 3
    if age_days <= 365:
        return 2
    if age_days <= 730:
        return 1
    return 0


def segment_for_units(units):
    if units <= 15:
        return "SMALL"
    if units <= 100:
        return "MEDIUM"
    return "LARGE"


def quota_limit_for_segment(segment):
    if segment == "SMALL":
        return 1
    if segment == "MEDIUM":
        return 3
    return 6


def utilization_factor_for(annual_vmt, average_power_units):
    divisor = average_power_units if average_power_units and average_power_units > 0 else 1
    ratio = dec(annual_vmt) / dec(divisor)
    if ratio < 20000:
        return Decimal("1.0")
    if ratio < 60000:
        return Decimal("1.2")
    if ratio < 100000:
        return Decimal("1.5")
    return Decimal("1.8")


def power_unit_exposure(average_power_units, utilization_factor):
    exposure = dec(average_power_units) * dec(utilization_factor)
    floor = Decimal("1.0")
    return exposure if exposure > floor else floor


def credit_tier(iss_pre_credit_value):
    value = dec(iss_pre_credit_value)
    if value >= Decimal("75.0"):
        return Decimal("0.06")
    if value >= Decimal("50.0"):
        return Decimal("0.04")
    return Decimal("0.02")


def band_for_iss(iss_value):
    value = dec(iss_value)
    if value >= BAND_INSPECT_MIN:
        return "INSPECT"
    if value >= BAND_OPTIONAL_MIN:
        return "OPTIONAL"
    return "PASS"


def percentile_for(certified_measure, threshold):
    """Piecewise-linear percentile mapping from the already-rounded measure."""
    m = dec(certified_measure)
    if threshold is None:
        return Decimal("0.0")
    p50 = dec(threshold["measure_at_p50"])
    p65 = dec(threshold["measure_at_p65"])
    p80 = dec(threshold["measure_at_p80"])
    if m <= 0:
        return Decimal("0.0")
    if m <= p50:
        return rhu(Decimal("50.0") * m / p50, 1)
    if m <= p65:
        return rhu(Decimal("50.0") + Decimal("15.0") * (m - p50) / (p65 - p50), 1)
    if m <= p80:
        return rhu(Decimal("65.0") + Decimal("15.0") * (m - p65) / (p80 - p65), 1)
    raw = Decimal("80.0") + Decimal("20.0") * (m - p80) / p80
    if raw > Decimal("100.0"):
        raw = Decimal("100.0")
    return rhu(raw, 1)
