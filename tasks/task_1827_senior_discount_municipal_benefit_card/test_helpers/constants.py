"""Domain thresholds — numeric constants named in the PRD."""

# The logical clock starts here at server startup (PRD §2.4).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.1: eligibility gates evaluated at submission against the clock.
    "MIN_AGE_YEARS": 65,
    "INCOME_LIMIT_CENTS": 2400000,          # $24,000 per year
    # PRD §3.6: per-cardholder monthly discount ceiling ($50).
    "CARDHOLDER_MONTHLY_DISCOUNT_CAP_CENTS": 5000,
    # PRD §3.6: velocity windows (calendar-day auto-flag, trailing-24h reject).
    "CALENDAR_DAY_FLAG_THRESHOLD": 5,
    "TRAILING_24H_REJECT_THRESHOLD": 10,
    # PRD §3.7: fraud-flag count that suspends a cardholder.
    "FRAUD_SUSPEND_THRESHOLD": 3,
    # PRD §3.3: recertification window / period; §3.4 card validity.
    "RECERTIFICATION_WINDOW_DAYS": 60,
    "RECERTIFICATION_PERIOD_DAYS": 365,
    "CARD_VALIDITY_YEARS": 2,
}

TEST_DEFAULTS = {
    "DATE_OF_BIRTH": "1955-01-01",          # age 71 at the default clock
    "ANNUAL_INCOME_CENTS": 500000,
    "RESIDENCY_ADDRESS": "1 Test Way",
    "MERCHANT_RATE_PCT": 10,
    "MERCHANT_MONTHLY_CAP_CENTS": 100000,
    "OFFER_DISCOUNT_PCT": 10,
    "OFFER_MAX_DISCOUNT_CENTS": 100,
    "OFFER_VALID_FROM": "2026-01-01",
    "OFFER_VALID_UNTIL": "2027-01-01",
    "FUND_FISCAL_YEAR": 2026,
    "FUND_ALLOCATED_CENTS": 1000000,
}

# Well-formed but nonexistent identifiers used for 404 probes.
BOGUS_UUID_1 = "11111111-1111-4111-8111-111111111111"
BOGUS_UUID_2 = "22222222-2222-4222-8222-222222222222"
BOGUS_UUID_4 = "44444444-4444-4444-8444-444444444444"
BOGUS_UUID_5 = "55555555-5555-4555-8555-555555555555"
BOGUS_UUID_6 = "66666666-6666-4666-8666-666666666666"
