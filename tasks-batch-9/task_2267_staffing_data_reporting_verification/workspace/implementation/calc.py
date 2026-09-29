"""Pure numeric machinery: rounding, shift arithmetic, and the tier tables.

Every quantity rounds half up (PRD 2.5).  Three precisions are in play: hour
quantities at 2 decimal places, ratios and per-resident-day rates at 4, and
money as whole cents.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")

# calculations.hour_entry_classification
MINUTES_PER_HOUR = Decimal(60)
ALLOCATION_PERCENT_TOTAL = Decimal("100.00")
MAX_SHIFT_HOURS = Decimal("16.00")
MAX_HOURS_PER_DAY = Decimal("24.00")
MAX_REPORTED_HOURS_PER_WORKER_DAY = Decimal("20.00")

# calculations.hprd_reconciliation
MAX_PLAUSIBLE_HPRD = Decimal("12.0000")

# calculations.census_variance_reconciliation
CENSUS_VARIANCE_TOLERANCE = Decimal("0.0500")

# calculations.staffing_rating_assignment
TOTAL_TIERS = (
    (Decimal("3.6000"), 5),
    (Decimal("3.0000"), 4),
    (Decimal("2.4000"), 3),
    (Decimal("1.8000"), 2),
)
RN_TIERS = (
    (Decimal("0.7500"), 5),
    (Decimal("0.5500"), 4),
    (Decimal("0.3500"), 3),
    (Decimal("0.2000"), 2),
)
WEEKEND_HPRD_FLOOR = Decimal("2.4000")
ZERO_RN_DAY_LIMIT = 4

# calculations.audit_support_score
W_SUPPORT = Decimal("0.50")
W_VENDOR = Decimal("0.30")
W_CENSUS = Decimal("0.20")
SAMPLE_SIZE = 5
AUDIT_RISK_FLOOR = Decimal("70.00")

# calculations.amendment_surcharge
BASE_AMENDMENT_FEE_CENTS = 25000
ESCALATION_STEP_CENTS = 2500
TIER_HIGH_FLOOR_CENTS = 27500
TIER_MID_FLOOR_CENTS = 25000
LATE_RATE_TIER_HIGH = Decimal("0.0300")
LATE_RATE_TIER_MID = Decimal("0.0200")
LATE_RATE_TIER_LOW = Decimal("0.0100")
LATE_RATE_TIER_ZERO = Decimal("0.0000")
SECONDS_PER_DAY = 86400
SURCHARGE_CAP_CENTS = 50000

APPEAL_WINDOW_DAYS = 30


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def r2(value):
    return dec(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r4(value):
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def rcents(value):
    return int(dec(value).quantize(Q0, rounding=ROUND_HALF_UP))


def sum2(values):
    total = Decimal(0)
    for value in values:
        total += dec(value)
    return r2(total)


def ratio4(numerator, denominator):
    """A 4-decimal quotient, or None when the denominator is zero."""
    if denominator == 0:
        return None
    return r4(dec(numerator) / Decimal(denominator))


def is_weekend_date(day):
    return day.weekday() in (5, 6)


def date_range(start, end):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor = cursor + timedelta(days=1)


def parse_iso_date(text):
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def shift_minutes(start_minutes, end_minutes):
    return end_minutes - start_minutes


def raw_hours_from_minutes(minutes):
    return r2(Decimal(minutes) / MINUTES_PER_HOUR)


def classify_allocations(raw_hours, lines, categories):
    """calculations.hour_entry_classification.

    ``lines`` are processed in the exact order supplied — the array order is the
    pinned processing order.  Each line is rounded to 2 decimal places BEFORE
    the lines are summed; summing unrounded values and rounding once is a
    different, incorrect result.
    """
    direct = Decimal(0)
    rn = Decimal(0)
    lpn = Decimal(0)
    na = Decimal(0)
    for line in lines:
        category = categories[line["job_category_id"]]
        credit = dec(category["direct_care_credit_pct"])
        contribution = r2(raw_hours * (dec(line["percent"]) / Decimal(100)) * credit)
        direct += contribution
        group = category.get("nurse_group")
        if group == "RN":
            rn += contribution
        elif group == "LPN":
            lpn += contribution
        elif group == "NA":
            na += contribution
    direct = r2(direct)
    return {
        "direct_care_hours": direct,
        "excluded_hours": r2(dec(raw_hours) - direct),
        "rn_hours": r2(rn),
        "lpn_hours": r2(lpn),
        "na_hours": r2(na),
    }


def allocation_percent_total(lines):
    total = Decimal(0)
    for line in lines:
        total += dec(line["percent"])
    return total


def tier_points(value, tiers):
    """A null hours-per-resident-day figure scores 1 point on that dimension."""
    if value is None:
        return 1
    for floor, points in tiers:
        if dec(value) >= floor:
            return points
    return 1


def star_rating(total_nurse_hprd, rn_hprd, weekend_total_nurse_hprd, days_with_zero_rn_hours):
    """calculations.staffing_rating_assignment, four steps in order."""
    total_points = tier_points(total_nurse_hprd, TOTAL_TIERS)
    rn_points = tier_points(rn_hprd, RN_TIERS)
    base_star = min(total_points, rn_points)
    if weekend_total_nurse_hprd is None or dec(weekend_total_nurse_hprd) < WEEKEND_HPRD_FLOOR:
        star = max(1, base_star - 1)
    else:
        star = base_star
    rating = 1 if days_with_zero_rn_hours >= ZERO_RN_DAY_LIMIT else star
    return total_points, rn_points, rating


def census_variance(resident_count, mds_resident_count):
    """calculations.census_variance_reconciliation."""
    if mds_resident_count is None:
        return None
    if mds_resident_count == 0:
        return Decimal("0.0000") if resident_count == 0 else Decimal("1.0000")
    return r4(Decimal(abs(resident_count - mds_resident_count)) / Decimal(mds_resident_count))


def late_rate_for(base_fee_cents):
    """The tier is keyed on the base fee, never on the eventual total."""
    if base_fee_cents >= TIER_HIGH_FLOOR_CENTS:
        return LATE_RATE_TIER_HIGH
    if base_fee_cents >= TIER_MID_FLOOR_CENTS:
        return LATE_RATE_TIER_MID
    if base_fee_cents >= 1:
        return LATE_RATE_TIER_LOW
    return LATE_RATE_TIER_ZERO


def amendment_surcharge_cents(status, amendment_index, deadline, now):
    """calculations.amendment_surcharge, evaluation order pinned."""
    amendment_index_after = amendment_index + 1
    if status == "REJECTED":
        base_fee_cents = 0
    else:
        base_fee_cents = BASE_AMENDMENT_FEE_CENTS + ESCALATION_STEP_CENTS * (amendment_index_after - 1)

    seconds_late = int((now - deadline).total_seconds())
    if seconds_late <= 0:
        late_days = 0
    else:
        late_days = -(-seconds_late // SECONDS_PER_DAY)

    late_rate = late_rate_for(base_fee_cents)
    late_fee_cents = rcents(Decimal(base_fee_cents) * late_rate * Decimal(late_days))
    return base_fee_cents + late_fee_cents
