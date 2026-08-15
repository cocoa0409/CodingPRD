"""Domain thresholds and rate constants from the PRD's calculation sections."""

# Underwriting-class multipliers (PRD §3.3).
CLASS_MULTIPLIER = {
    "PREFERRED_NON_TOBACCO": 0.90,
    "STANDARD_NON_TOBACCO": 1.00,
    "PREFERRED_TOBACCO": 1.50,
    "STANDARD_TOBACCO": 1.80,
    "SUBSTANDARD_TABLE_B": 2.00,
    "SUBSTANDARD_TABLE_D": 2.50,
}

# Substandard extra mortality loading stamped at approval (PRD §3.2).
SUBSTANDARD_EXTRA_PCT_BPS = {
    "PREFERRED_NON_TOBACCO": 0,
    "STANDARD_NON_TOBACCO": 0,
    "PREFERRED_TOBACCO": 0,
    "STANDARD_TOBACCO": 0,
    "SUBSTANDARD_TABLE_B": 2500,
    "SUBSTANDARD_TABLE_D": 5000,
}

# Mode factors applied after the monthly rate is rounded (PRD §3.3).
MODE_FACTOR = {
    "MONTHLY": 1.00,
    "QUARTERLY": 2.94,
    "SEMI_ANNUAL": 5.82,
    "ANNUAL": 11.52,
}

# Policy-loan interest: carrier-fixed 500 bps per annum over a 365-day year (PRD §3.6).
LOAN_ANNUAL_INTEREST_RATE_BPS = 500
DAYS_PER_YEAR = 365

# Grace period length in days (PRD §3.4).
GRACE_PERIOD_DAYS = 31

# Reinstatement interest rate per annum (PRD §3.9).
REINSTATEMENT_ANNUAL_RATE = 0.06

# Conversion / reinstatement windows: five years (PRD §3.9, §3.10).
WINDOW_YEARS = 5

# Reduced paid-up conversion-rate bands by attained age (PRD §3.8).
def reduced_paid_up_rate(attained_age: int, substandard_extra_pct_bps: int = 0) -> float:
    if attained_age < 40:
        rate = 0.30
    elif attained_age < 50:
        rate = 0.40
    elif attained_age < 60:
        rate = 0.50
    else:
        rate = 0.65
    return rate + substandard_extra_pct_bps / 10000 * 0.10


# Extended-term monthly cost rate per dollar of face by attained age (PRD §3.8).
def extended_term_monthly_cost_rate(attained_age: int) -> float:
    if attained_age < 40:
        return 0.0010
    if attained_age < 50:
        return 0.0020
    if attained_age < 60:
        return 0.0040
    return 0.0090


# Extended-term duration cap in months (PRD §3.8).
EXTENDED_TERM_MAX_MONTHS = 60

# Server startup default for the logical clock (PRD §2.4).
CLOCK_START = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "FULL_NAME": "Test Insured",
    "DATE_OF_BIRTH": "1990-01-01",
    "GENDER": "FEMALE",
    "FACE_AMOUNT_CENTS": 10_000_000,          # $100,000
    "BASE_RATE_PER_THOUSAND_CENTS": 50,
    "MIN_FACE_CENTS": 1_000_000,
    "MAX_FACE_CENTS": 100_000_000,
    "PREMIUM_MODE": "MONTHLY",
    "UNDERWRITING_CLASS": "STANDARD_NON_TOBACCO",
}
