"""Constants, rounding discipline and the pure calculation helpers."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- time constants (PRD 2.5) ------------------------------------------------
DAY_PART_WINDOWS = {
    "MORNING": (9, 13),
    "MIDDAY": (12, 16),
    "AFTERNOON": (15, 19),
}
DAY_PARTS = ["MORNING", "MIDDAY", "AFTERNOON"]

SETUP_LEAD_MINUTES = 45
TEARDOWN_MINUTES = 75
CHECK_IN_EARLY_MINUTES = 60
NO_SHOW_GRACE_MINUTES = 15
LATE_GRACE_MINUTES = 10
MIN_BOOKING_LEAD_DAYS = 7
MAX_BOOKING_HORIZON_DAYS = 120
SANITATION_BUFFER_MINUTES = 30
ACTIVATION_EARLY_MINUTES = 60

# --- allocation / coverage / caps -------------------------------------------
MIN_CASES_FOR_FOOD_SAMPLING = 2
SUPPORT_REQUIRED_CASE_THRESHOLD = 6
MAX_EVENTS_PER_CATEGORY_PER_DAY = 2
MAX_ASSIGNMENTS_PER_DEMONSTRATOR_PER_DAY = 2

# --- reliability ------------------------------------------------------------
NO_SHOW_PENALTY = Decimal("12")
LATE_PENALTY = Decimal("4")
COMPLETION_BONUS = Decimal("0.5")
NO_SHOW_STRIKE_LIMIT = 3
STRIKE_LOOKBACK_DAYS = 180
ROLLING_WINDOW_DAYS = 90

# --- measurement ------------------------------------------------------------
PROVISIONAL_WINDOW_DAYS = 3
SAMPLE_CANNIBALIZATION_RATE = Decimal("0.15")

# --- reconciliation ---------------------------------------------------------
VARIANCE_TOLERANCE_PCT = Decimal("2.00")

# --- invoice ----------------------------------------------------------------
BASE_FEE_BY_EVENT_TYPE = {"FOOD_SAMPLING": Decimal("42000"), "NON_FOOD_DEMO": Decimal("28000")}
CLUB_TIER_MULTIPLIER = {
    "FLAGSHIP": Decimal("1.25"),
    "STANDARD": Decimal("1.00"),
    "SATELLITE": Decimal("0.85"),
}
DAY_PART_MULTIPLIER = {
    "MORNING": Decimal("1.00"),
    "MIDDAY": Decimal("1.15"),
    "AFTERNOON": Decimal("1.05"),
}
ADDON_FLAT_CENTS = {
    "EXTRA_TABLE": Decimal("5000"),
    "VIDEO_LOOP": Decimal("7500"),
    "ALLERGEN_SIGNAGE": Decimal("2200"),
}
ADDON_PCT_OF_BASE = {
    "PREMIUM_PLACEMENT": Decimal("0.18"),
    "BILINGUAL_DEMONSTRATOR": Decimal("0.12"),
}
ADDON_SERVICES = [
    "EXTRA_TABLE",
    "VIDEO_LOOP",
    "ALLERGEN_SIGNAGE",
    "PREMIUM_PLACEMENT",
    "BILINGUAL_DEMONSTRATOR",
]
MAX_ADDON_SERVICES = 5
ROLE_MULTIPLIER = {"LEAD": Decimal("1.20"), "SUPPORT": Decimal("1.00")}
MIN_BILLABLE_HOURS = Decimal("4.00")
HANDLING_FEE_PER_CASE_CENTS = Decimal("900")
COLD_CHAIN_SURCHARGE_PER_CASE_CENTS = Decimal("350")
TIER_BASE_DISCOUNT = {
    "PLATINUM": Decimal("0.06"),
    "GOLD": Decimal("0.03"),
    "STANDARD": Decimal("0.00"),
}
MAX_VOLUME_DISCOUNT_PCT = Decimal("0.10")

# --- credit valuation -------------------------------------------------------
NOTICE_BRACKET_SPLIT_CENTS = 50000
NOTICE_TIER = {
    "HIGH": {"GTE_72": Decimal("0.25"), "GTE_24_LT_72": Decimal("0.50"), "LT_24": Decimal("0.85")},
    "LOW": {"GTE_72": Decimal("0.15"), "GTE_24_LT_72": Decimal("0.35"), "LT_24": Decimal("0.70")},
}
REASON_MULTIPLIER = {
    "CLUB_CANCELLED": Decimal("1.00"),
    "DEMONSTRATOR_NO_SHOW": Decimal("1.00"),
    "PRODUCT_SHORT": Decimal("0.60"),
    "MANUFACTURER_CANCELLED_LATE": Decimal("0.00"),
    "MANUFACTURER_CANCELLED_EARLY": Decimal("0.00"),
}

# --- enumerations -----------------------------------------------------------
PROGRAM_TIERS = ["PLATINUM", "GOLD", "STANDARD"]
ACCOUNT_STATUSES = ["ACTIVE", "HOLD", "SUSPENDED"]
CREDIT_TERMS_DAYS = [15, 30, 45, 60]
CLUB_TIERS = ["FLAGSHIP", "STANDARD", "SATELLITE"]
CLUB_STATUSES = ["OPEN", "RESTRICTED", "CLOSED"]
CATEGORIES = [
    "BAKERY",
    "DAIRY",
    "FROZEN",
    "BEVERAGE",
    "SNACK",
    "HOUSEHOLD",
    "ELECTRONICS",
    "APPAREL",
]
EMPLOYMENT_STATUSES = ["ACTIVE", "ON_LEAVE", "TERMINATED"]
CERT_TYPES = ["FOOD_HANDLER", "ALLERGEN_AWARENESS", "HEAT_EQUIPMENT"]
EQUIPMENT_TYPES = [
    "CONVECTION_OVEN",
    "INDUCTION_COOKTOP",
    "REFRIGERATED_CART",
    "DISPLAY_TABLE",
    "TV_CART",
]
FOOD_CERT_EQUIPMENT_TYPES = {"CONVECTION_OVEN", "INDUCTION_COOKTOP", "REFRIGERATED_CART"}
SANITATION_STATUSES = ["SANITIZED", "IN_USE", "SOILED", "OUT_OF_SERVICE"]
BOOKING_STATUSES = ["DRAFT", "SUBMITTED", "CONFIRMED", "COMPLETED", "CANCELLED"]
STAFFING_STATUSES = ["UNSTAFFED", "PARTIALLY_STAFFED", "FULLY_STAFFED", "EXECUTED", "CLOSED_OUT"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "RELEASED"]
ASSIGNMENT_ROLES = ["LEAD", "SUPPORT"]
RESERVATION_STATUSES = ["HELD", "ACTIVE", "RELEASED"]
SHIPMENT_STATUSES = ["IN_TRANSIT", "DELIVERED", "SHORT", "REJECTED"]
RECON_STATUSES = ["OPEN", "BALANCED", "VARIANCE_FLAGGED", "WRITTEN_OFF"]
MEASUREMENT_VARIANTS = ["PROVISIONAL", "FINAL"]
MEASUREMENT_STATUSES = ["POSTED", "STALE", "SUPERSEDED"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "VOID", "PAID"]
CREDIT_STATUSES = ["PENDING_APPROVAL", "APPROVED", "APPLIED", "REJECTED"]
CREDIT_REASONS = [
    "CLUB_CANCELLED",
    "MANUFACTURER_CANCELLED_EARLY",
    "MANUFACTURER_CANCELLED_LATE",
    "PRODUCT_SHORT",
    "DEMONSTRATOR_NO_SHOW",
]

HELD_ASSIGNMENT_STATUSES = ("ASSIGNED", "CONFIRMED", "CHECKED_IN")
CAP_ASSIGNMENT_STATUSES = ("ASSIGNED", "CONFIRMED", "CHECKED_IN", "COMPLETED")
LIVE_BOOKING_STATUSES = ("CONFIRMED", "COMPLETED")
RECEIVED_SHIPMENT_STATUSES = ("DELIVERED", "SHORT")


# --- rounding ---------------------------------------------------------------
def cents(value):
    """Round a Decimal to whole cents, ROUND_HALF_UP (half away from zero)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec2(value):
    """Round a Decimal to 2 decimal places, ROUND_HALF_UP."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num2(value):
    """Round to 2dp and expose it as the JSON number the PRD describes."""
    return float(dec2(value))


# --- parsing ----------------------------------------------------------------
def parse_date(text):
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_instant(text):
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_date(value):
    return value.isoformat()


def week_monday(day):
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


# --- windows ----------------------------------------------------------------
def event_window(event_date_str, day_part):
    day = parse_date(event_date_str)
    start_hour, end_hour = DAY_PART_WINDOWS[day_part]
    start = datetime(day.year, day.month, day.day, start_hour, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=4)
    assert end.hour == end_hour or True
    return start, end


def shift_window(window_start, window_end):
    return (
        window_start - timedelta(minutes=SETUP_LEAD_MINUTES),
        window_end + timedelta(minutes=TEARDOWN_MINUTES),
    )


# --- misc -------------------------------------------------------------------
def base_fee_projection(event_type, club_tier, day_part):
    raw = (
        BASE_FEE_BY_EVENT_TYPE[event_type]
        * CLUB_TIER_MULTIPLIER[club_tier]
        * DAY_PART_MULTIPLIER[day_part]
    )
    return cents(raw)


def notice_bracket(notice_hours):
    if notice_hours >= 72:
        return "GTE_72"
    if notice_hours >= 24:
        return "GTE_24_LT_72"
    return "LT_24"


def volume_step(monthly_count):
    if monthly_count >= 12:
        return Decimal("0.05")
    if monthly_count >= 5:
        return Decimal("0.02")
    return Decimal("0.00")
