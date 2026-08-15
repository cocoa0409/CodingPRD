"""Domain thresholds — numeric constants named in the PRD."""

# The logical clock before any operator sets it (PRD: the clock "reads
# exactly 2026-08-01T00:00:00Z" before being advanced).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Scholarship policy defaults applied when the optional knobs are omitted.
DEFAULT_MAX_AWARD_PCT_BP = 5000          # 10000 basis points == 100%
DEFAULT_PER_REGISTRATION_CAP_CENTS = 150000
DEFAULT_CHAPERONE_RATIO = 5

# Donation processing fees per channel.
CARD_FEE_PCT = 0.029                     # percentage component, rounded half up first
CARD_FEE_FLAT_CENTS = 30
CHECK_FEE_FLAT_CENTS = 25
CASH_FEE_CENTS = 0

# Late-fee rule: the greater of the flat amount and the rounded percentage.
LATE_FEE_FLAT_CENTS = 2500
LATE_FEE_PCT = 0.05

# Screening / discipline durations (days).
SCREENING_VALIDITY_DAYS = 730            # expires_at = cleared_at + 730 days
BARRED_DURATION_DAYS = 730               # barred_until = dismissal clock + 730 days

# Need-score points.
NEED_INCOME_BASE = {"BAND_A": 50, "BAND_B": 35, "BAND_C": 20, "BAND_D": 5,
                    "UNDISCLOSED": 0}
NEED_SIZE_BONUS_PER_EXTRA_PERSON = 5
NEED_SIZE_BONUS_CAP = 20
NEED_SIBLING_BONUS_EACH = 10
NEED_SIBLING_BONUS_CAP = 20
NEED_FUNDRAISING_GOAL_MET = 10
NEED_FUNDRAISING_ANY_GROSS = 5
NEED_SCORE_CAP = 100

# Vehicle turnaround buffer between TRAVEL items sharing a vehicle_code.
VEHICLE_TURNAROUND_MINUTES = 45

# Nonexistent but well-formed UUID used to probe typed 404s.
MISSING_UUID = "11111111-1111-4111-8111-111111111111"


def round_half_up_cents(numerator: float) -> int:
    """Round a fractional cent amount half up to the nearest integer cent."""
    import decimal
    return int(decimal.Decimal(str(numerator)).quantize(
        0, rounding=decimal.ROUND_HALF_UP))
