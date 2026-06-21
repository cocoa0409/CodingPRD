from decimal import Decimal, ROUND_HALF_UP

# Constants
CSED_BASE_DAYS = 3653
AGREEMENT_BUFFER_DAYS = 30
SHORT_TERM_MAX_MONTHS = 6
MISSED_DEBIT_DEFAULT_THRESHOLD = 2

STANDARD_FTP_RATE = Decimal("0.005")
DDIA_FTP_RATE = Decimal("0.0025")
MONTHLY_INTEREST_RATE = Decimal("0.006")

DDIA_SETUP_FEE_CENTS = 3100
MANUAL_SETUP_FEE_CENTS = 14900

MULT_SHORT = 12
MULT_MID = 24
MULT_LONG = 60


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def full_calendar_months(assessment_date, current_utc):
    """Number of full calendar months from assessment_date to current_utc (floor)."""
    if current_utc <= assessment_date:
        return 0
    months = (current_utc.year - assessment_date.year) * 12 + (
        current_utc.month - assessment_date.month
    )
    # Subtract one if we haven't reached the same day-of-month/time in the final month.
    if (current_utc.day, current_utc.hour, current_utc.minute, current_utc.second,
        current_utc.microsecond) < (
            assessment_date.day, assessment_date.hour, assessment_date.minute,
            assessment_date.second, assessment_date.microsecond):
        months -= 1
    return max(0, months)


def accrued_penalty_cents(assessed_tax_cents, months_elapsed, ddia_reduced):
    rate = DDIA_FTP_RATE if ddia_reduced else STANDARD_FTP_RATE
    total = 0
    per_month = round_half_up(Decimal(assessed_tax_cents) * rate)
    total = per_month * months_elapsed
    return total


def accrued_interest_cents(assessed_tax_cents, months_elapsed):
    # sum-then-round: round once after multiplying
    return round_half_up(
        Decimal(assessed_tax_cents) * MONTHLY_INTEREST_RATE * Decimal(months_elapsed)
    )


def setup_fee_cents(low_income_flag, agreement_type, payment_method):
    if low_income_flag:
        return 0
    if agreement_type == "SHORT_TERM":
        return 0
    if payment_method == "DIRECT_DEBIT":
        return DDIA_SETUP_FEE_CENTS
    return MANUAL_SETUP_FEE_CENTS


def rcp_multiplier(remaining_months):
    if remaining_months <= 0:
        return 0
    if remaining_months <= 24:
        return MULT_SHORT
    if remaining_months <= 60:
        return MULT_MID
    return MULT_LONG
