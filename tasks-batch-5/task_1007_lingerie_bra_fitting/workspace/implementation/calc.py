"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5-2.7, §3).

All monetary math uses Decimal with round-half-up; never float. (PRD §2.5)
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

# --- constants (SCAFFOLD §1.3) ---------------------------------------------
CM_PER_INCH = Decimal("2.54")
CUP_STEP_CM = Decimal("2.5")
CUP_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G", 8: "H"}

UNDERBUST_MIN_CM = 55
UNDERBUST_MAX_CM = 120
BUST_MIN_CM = 60
BUST_MAX_CM = 170

SIZE_SURCHARGE_CENTS = 500
EXTENDED_BAND_MIN = 40
EXTENDED_CUPS = {"F", "G", "H"}  # F and larger

TIER_DISCOUNT_PCT = {"BRONZE": Decimal("0.00"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
GIFT_WRAP_FEE_CENTS = 800
SPECIAL_ORDER_FEE_CENTS = 1500

POINTS_DIVISOR_CENTS = 100
TIER_MULTIPLIER = {"BRONZE": 1, "SILVER": 1, "GOLD": 2}

COVERAGE_PCT = Decimal("0.80")
COVERAGE_CAP_CENTS = 50000

LOW_STOCK_THRESHOLD = 3

FITTER_BUFFER_MIN = 15

SILVER_THRESHOLD = 1000
GOLD_THRESHOLD = 5000

REPLACEMENT_INTERVAL_MONTHS = 6
EXCHANGE_WINDOW_DAYS = 30


def round_half_up(dec):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_cents(base_cents, pct):
    """round_half_up(base_cents * pct) -> integer cents (PRD §2.5)."""
    return round_half_up(Decimal(int(base_cents)) * Decimal(pct))


# --- loyalty tier (SCAFFOLD calc loyalty_tier) -----------------------------
def loyalty_tier(points):
    if points >= GOLD_THRESHOLD:
        return "GOLD"
    if points >= SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


# --- SKU price (calc sku_price) --------------------------------------------
def sku_price(base_price_cents, band_size, cup_size):
    extended = band_size >= EXTENDED_BAND_MIN or cup_size in EXTENDED_CUPS
    return int(base_price_cents) + (SIZE_SURCHARGE_CENTS if extended else 0)


# --- SKU stock status (calc sku_stock_status) ------------------------------
def stock_status(available_units):
    if available_units <= 0:
        return "OUT_OF_STOCK"
    if available_units <= LOW_STOCK_THRESHOLD:
        return "LOW_STOCK"
    return "IN_STOCK"


# --- bra size recommendation (calc bra_size_recommendation) ----------------
class MeasurementOutOfRange(Exception):
    pass


def bra_size(underbust_cm, bust_cm, fit_preference):
    """Returns (recommended_band:int, recommended_cup:str, recommended_size:str).

    Raises MeasurementOutOfRange when the derived cup index falls outside 1..8.
    (Numeric range on the raw measurements is enforced by the caller.)
    """
    ub = Decimal(str(underbust_cm))
    bu = Decimal(str(bust_cm))
    raw_band = ub / CM_PER_INCH
    half = raw_band / Decimal(2)
    if fit_preference == "SNUG":
        band = int(half.to_integral_value(rounding=ROUND_FLOOR)) * 2
    elif fit_preference == "RELAXED":
        band = int(half.to_integral_value(rounding=ROUND_CEILING)) * 2
    else:  # STANDARD
        band = int(half.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * 2

    cup_diff = bu - ub
    cup_index = int((cup_diff / CUP_STEP_CM).to_integral_value(rounding=ROUND_CEILING))
    if cup_index < 1 or cup_index > 8:
        raise MeasurementOutOfRange()
    cup = CUP_LETTERS[cup_index]
    return band, cup, f"{band}{cup}"


# --- insurance coverage (calc insurance_coverage) --------------------------
def insurance_coverage(base_amount_cents):
    return min(pct_cents(base_amount_cents, COVERAGE_PCT), COVERAGE_CAP_CENTS)


# --- loyalty points (calc loyalty_points_earned) ---------------------------
def base_points(total_cents):
    return int(total_cents) // POINTS_DIVISOR_CENTS  # floor on division


def final_points(total_cents, tier):
    return base_points(total_cents) * TIER_MULTIPLIER[tier]


# --- calendar-month add (calc replacement_reminder_due_date) ---------------
def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to last valid day of the target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def whole_days_between(later, earlier):
    """Whole days elapsed from `earlier` to `later` (floor)."""
    delta = later - earlier
    return delta.days if delta.days >= 0 else -((-delta).days)
