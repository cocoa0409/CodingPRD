"""Plan arithmetic: surcharge points, premium, expense charge, deposits,
earned premium, apportionment, exposure and penalties.

Every monetary quantity is an integer number of cents and every derived money
figure is rounded half up (PRD Section 2.7).  Decimal is used throughout; float
never touches a monetary computation.
"""

from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from store import days, whole_days

# ---------------------------------------------------------------- constants
VIOLATION_POINTS = {
    "SPEEDING_MINOR": 1,
    "SPEEDING_MAJOR": 3,
    "AT_FAULT_ACCIDENT": 3,
    "LICENSE_SUSPENSION": 4,
    "RECKLESS_DRIVING": 5,
    "DUI": 8,
}

DRIVER_CLASS_POINT_ADDER = {"ADULT": 0, "SENIOR": 1, "YOUTHFUL_OPERATOR": 3}

POINTS_CAP = 15
EXPERIENCE_WINDOW_DAYS = 1095

TERRITORY_BASE_ANNUAL_CENTS = {"T01": 96475, "T02": 148337, "T03": 231909}

LINE_SHARES = (("BI", Decimal("0.55")), ("PD", Decimal("0.30")), ("UM", Decimal("0.15")))

CLASS_FACTORS = {
    "PLEASURE": Decimal("1.00"),
    "WORK_LT10": Decimal("1.10"),
    "WORK_GE10": Decimal("1.25"),
    "BUSINESS": Decimal("1.45"),
}

EXPENSE_TIER_1_CEILING_CENTS = 75000
EXPENSE_TIER_2_CEILING_CENTS = 150000
EXPENSE_RATE_TIER_1 = Decimal("0.06")
EXPENSE_RATE_TIER_2 = Decimal("0.05")
EXPENSE_RATE_TIER_3 = Decimal("0.04")

DEPOSIT_PERCENT = Decimal("0.25")
DEPOSIT_FLOOR_CENTS = 15000

DAYS_PER_YEAR = 365
SHORT_RATE_PENALTY_MULTIPLIER = Decimal("1.10")
SHORT_RATE_MINIMUM_CENTS = 5000

CLEAN_YEARS_CAP = 5
VOLUNTARY_EXIT_MIN_CLEAN_YEARS = 3

CAR_YEAR_DECIMALS = 4
DEFICIENCY_PENALTY_CENTS_PER_UNIT = Decimal("25000")

STANDARD_CREDIT_UNITS = Decimal("1.0")
UNDERSERVED_CREDIT_MULTIPLIER = Decimal("1.5")

VOLUNTARY_REJECTION_LOOKBACK_DAYS = 90
MIN_DISTINCT_REJECTIONS = 2

ACCEPTANCE_WINDOW_DAYS = 10
CLAIM_ACK_WINDOW_DAYS = 10

SCORE_START = 100
SCORE_FLOOR = 0
SCORE_CEILING = 100
ACK_BREACH_DEDUCTION = 5
UPHELD_COMPLAINT_DEDUCTION = 20
MISSED_ISSUANCE_DEDUCTION = 5
PERIOD_CLOSURE_RECOVERY = 10
SUSPENSION_SCORE_CEILING = 70
RESTRICTION_SCORE_CEILING = 85
BREACH_RESTRICTION_THRESHOLD = 3

NON_RENEWAL_PERIOD_CAP = 3
CURE_LIMIT = 2
REVIEW_ROUND_LIMIT = 3
NON_RENEWAL_NOTICE_LEAD_DAYS = 45
EXIT_NOTICE_LEAD_DAYS = 90
FIRST_PERIOD_CANCEL_DAYS = 60

RESTRICTED_LATE_TERM_REASONS = (
    "NON_PAYMENT_OF_PREMIUM",
    "LICENSE_SUSPENDED",
    "MATERIAL_MISREPRESENTATION",
    "INSURED_REQUEST",
)


# ------------------------------------------------------------------ helpers
def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        if isinstance(value, Fraction):
            value = Decimal(value.numerator) / Decimal(value.denominator)
        else:
            value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def dec1(value):
    return rhu(value, 1)


def dec4(value):
    return rhu(value, CAR_YEAR_DECIMALS)


# --------------------------------------------------------- surcharge points
def surcharge_points(violations, driver_class, rating_date):
    """Points from the in-window convictions plus the driver-class adder, capped."""
    lower_bound = rating_date - days(EXPERIENCE_WINDOW_DAYS)
    raw = 0
    for violation in violations or []:
        conviction_date = violation["conviction_date"]
        # strictly newer than rating_date - 1095 days, and not after rating_date
        if conviction_date > lower_bound and conviction_date <= rating_date:
            raw += VIOLATION_POINTS[violation["code"]]
    raw += DRIVER_CLASS_POINT_ADDER.get(driver_class, 0)
    return min(POINTS_CAP, raw)


def surcharge_factor(points):
    if points <= 0:
        return Decimal("1.00")
    if points <= 3:
        return Decimal("1.15")
    if points <= 5:
        return Decimal("1.35")
    if points <= 9:
        return Decimal("1.60")
    return Decimal("1.90")


# ---------------------------------------------------------- annual premium
def premium_lines(territory_code, vehicle_class_code, factor):
    """Per coverage line rounding, THEN sum (PRD Section 3.4)."""
    base = Decimal(TERRITORY_BASE_ANNUAL_CENTS[territory_code])
    klass = CLASS_FACTORS[vehicle_class_code]
    lines = {}
    for name, share in LINE_SHARES:
        lines[name] = rhu_cents(base * share * klass * factor)
    total = lines["BI"] + lines["PD"] + lines["UM"]
    return lines, total


def expense_rate(final_premium_cents):
    if final_premium_cents < EXPENSE_TIER_1_CEILING_CENTS:
        return EXPENSE_RATE_TIER_1
    if final_premium_cents < EXPENSE_TIER_2_CEILING_CENTS:
        return EXPENSE_RATE_TIER_2
    return EXPENSE_RATE_TIER_3


def expense_charge(final_premium_cents):
    return rhu_cents(Decimal(final_premium_cents) * expense_rate(final_premium_cents))


def rate(territory_code, vehicle_class_code, violations, driver_class, rating_date):
    """Full rating pass -> (points, factor, lines, final, charge, total)."""
    points = surcharge_points(violations, driver_class, rating_date)
    factor = surcharge_factor(points)
    lines, final = premium_lines(territory_code, vehicle_class_code, factor)
    charge = expense_charge(final)
    return points, factor, lines, final, charge, final + charge


# ------------------------------------------------------------------ deposit
def required_deposit(estimated_total_charge_cents):
    return max(
        rhu_cents(Decimal(estimated_total_charge_cents) * DEPOSIT_PERCENT),
        DEPOSIT_FLOOR_CENTS,
    )


# ----------------------------------------------- earned premium at cancel
def pro_rata_earned(total_annual_charge_cents, days_in_force):
    return rhu_cents(
        Decimal(total_annual_charge_cents) * Decimal(days_in_force) / Decimal(DAYS_PER_YEAR)
    )


def short_rate_earned(total_annual_charge_cents, days_in_force):
    inflated = rhu_cents(
        Decimal(total_annual_charge_cents)
        * Decimal(days_in_force)
        / Decimal(DAYS_PER_YEAR)
        * SHORT_RATE_PENALTY_MULTIPLIER
    )
    return min(total_annual_charge_cents, max(SHORT_RATE_MINIMUM_CENTS, inflated))


def earned_premium(total_annual_charge_cents, days_in_force, basis):
    if basis == "PRO_RATA":
        return pro_rata_earned(total_annual_charge_cents, days_in_force)
    return short_rate_earned(total_annual_charge_cents, days_in_force)


# ------------------------------------------------------------- clean years
def clean_years(clock, last_chargeable_event_date):
    elapsed = whole_days(clock, last_chargeable_event_date)
    if elapsed < 0:
        return 0
    return min(CLEAN_YEARS_CAP, elapsed // DAYS_PER_YEAR)


# ------------------------------------------------------- car-year exposure
def car_years(day_count):
    if day_count <= 0:
        return Decimal("0.0000")
    return dec4(Decimal(day_count) / Decimal(DAYS_PER_YEAR))


# ------------------------------------------------------------ apportionment
def largest_remainder(total, entries):
    """`entries` is a list of (key, share_bps, enrollment_sequence).

    Returns {key: whole units} summing exactly to `total`.
    """
    if not entries:
        return {}
    denominator = sum(e[1] for e in entries)
    if denominator <= 0 or total <= 0:
        return dict((e[0], 0) for e in entries)
    rows = []
    floors_sum = 0
    for key, share_bps, enrollment_sequence in entries:
        exact = Fraction(total * share_bps, denominator)
        floor_units = exact.numerator // exact.denominator
        remainder = exact - floor_units
        floors_sum += floor_units
        rows.append([key, share_bps, enrollment_sequence, floor_units, remainder])
    leftover = total - floors_sum
    rows.sort(key=lambda r: (-r[4], -r[1], r[2]))
    result = {}
    for index, row in enumerate(rows):
        result[row[0]] = row[3] + (1 if index < leftover else 0)
    return result


# ----------------------------------------------------------------- penalty
def deficiency_penalty(variance_units):
    shortfall = -variance_units if variance_units < 0 else Decimal("0")
    if shortfall <= 0:
        return 0
    return rhu_cents(shortfall * DEFICIENCY_PENALTY_CENTS_PER_UNIT)


# ------------------------------------------------- performance and posture
def clamp_score(value):
    return max(SCORE_FLOOR, min(SCORE_CEILING, value))


def posture_for(status, performance_score, breach_count_current_period, overallocated):
    """Ordered ladder -- the first matching rule wins (PRD Section 2.9)."""
    if status != "ACTIVE":
        return "SUSPENDED"
    if performance_score < SUSPENSION_SCORE_CEILING:
        return "SUSPENDED"
    if SUSPENSION_SCORE_CEILING <= performance_score <= RESTRICTION_SCORE_CEILING - 1:
        return "RESTRICTED"
    if breach_count_current_period >= BREACH_RESTRICTION_THRESHOLD:
        return "RESTRICTED"
    if overallocated:
        return "RESTRICTED"
    return "OPEN"
