"""Money and counting conventions (PRD 2.6).

All monetary amounts are integer cents.  Every non-integer amount is rounded
HALF UP.  Three computations depart from half-up and say so at the point of
use: the per-cycle credit cap uses floor, the ring failure rate is rounded
half up to four decimal places, and every minute/day count uses floor
division.  Decimal is used throughout; float never touches a cent.
"""

from decimal import Decimal, ROUND_HALF_UP

# PRD 2.6 / scaffold domain_constants -- every percentage is an exact Decimal.
SLA_AT_RISK_PCT = Decimal("0.80")
SLA_BREACH_TIER_MINOR_MAX_RATIO = Decimal("0.25")
SLA_BREACH_TIER_MAJOR_MAX_RATIO = Decimal("1.00")
SLA_CREDIT_PCT_MINOR = Decimal("0.05")
SLA_CREDIT_PCT_MAJOR = Decimal("0.15")
SLA_CREDIT_PCT_SEVERE = Decimal("0.30")
CREDIT_CAP_PCT_OF_MONTHLY_FEE = Decimal("0.50")
CSAT_BREACH_COMPOUNDED_CREDIT_PCT = Decimal("0.10")
CSAT_GOODWILL_CREDIT_PCT = Decimal("0.05")
ADVANCE_REPLACEMENT_HOLD_PCT_OF_MSRP = Decimal("0.60")
BUNDLE_DISCOUNT_TIER1_PCT = Decimal("0.10")
BUNDLE_DISCOUNT_TIER2_PCT = Decimal("0.15")

# Integer constants.
BUSINESS_HOURS_START_UTC_MINUTE = 540
BUSINESS_HOURS_END_UTC_MINUTE = 1020
CSAT_SURVEY_WINDOW_HOURS = 72
CSAT_LOW_SCORE_MAX = 2
ACTIVATION_TOKEN_TTL_MINUTES = 1440
ACTIVATION_MAX_ATTEMPTS = 3
REMOTE_FAILURE_ESCALATION_COUNT = 3
TRAVEL_BUFFER_MINUTES = 45
LATE_CANCEL_CUTOFF_HOURS = 24
LATE_CANCEL_FEE_CENTS = 4500
NO_SHOW_FEE_CENTS = 9000
FIRMWARE_DEFAULT_HALT_FAILURE_RATE_PCT = Decimal("0.20")
FIRMWARE_MAX_RETRY_COUNT = 2
FIRMWARE_DEFER_MAX_DAYS = 14
BILLING_CYCLE_DAYS = 30
PRORATION_MIN_DAYS = 5
BUNDLE_DISCOUNT_TIER1_MIN_SUBTOTAL_CENTS = 20000
BUNDLE_DISCOUNT_TIER2_MIN_SUBTOTAL_CENTS = 50000
INSTALL_VISIT_FEE_CENTS = 12900
ADDON_ORDER_MAX_LINES = 5
ADVANCE_REPLACEMENT_MIN_WARRANTY_DAYS = 30
RMA_RETURN_WINDOW_DAYS = 14
TICKET_REOPEN_WINDOW_HOURS = 168


def round_half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round to four decimal places, half up (the ring failure rate)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def floor_pct(cents, pct):
    """floor(cents * pct) -- used only by the per-cycle credit cap."""
    return int((Decimal(cents) * pct).to_integral_value(rounding="ROUND_FLOOR"))


def clamp_days(days):
    """Days remaining in a cycle: clamped below at 0 and above at 30."""
    return max(0, min(BILLING_CYCLE_DAYS, days))


def as_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))
