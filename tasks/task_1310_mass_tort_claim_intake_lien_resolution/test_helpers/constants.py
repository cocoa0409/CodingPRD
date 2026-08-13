"""Domain thresholds and numeric constants from PRD §2.5, §3.5, §3.7."""

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Attorney fee (PRD §3.7): 40% contingency, per-lien round-then-sum
FEE_RATE = 0.40

# Provisional lien demand discount rates (PRD §3.5)
PROVISIONAL_RATES = {
    "MEDICARE": 0.60,
    "MEDICAID": 0.50,
    "VA_TRICARE": 0.70,
    "PRIVATE_INSURER": 0.75,
}
MEDICAL_PROVIDER_HARDSHIP_RATE = 0.40
MEDICAL_PROVIDER_STANDARD_RATE = 0.80
HARDSHIP_FLOOR_CENTS = 5_000_000  # $50,000 gross award threshold

# Holder response window (PRD §3.5): 30 days from notify
HOLDER_RESPONSE_WINDOW_DAYS = 30

THRESHOLDS = {
    "HARDSHIP_FLOOR_CENTS": HARDSHIP_FLOOR_CENTS,
    "HOLDER_RESPONSE_WINDOW_DAYS": HOLDER_RESPONSE_WINDOW_DAYS,
    "MIN_GROUNDS_CHARS": 20,
    "MIN_RATIONALE_CHARS": 20,
    "MIN_ACCEPTED_RECORDS": 2,
}

TEST_DEFAULTS = {
    "QSF_PRINCIPAL_CENTS": 100_000_000,
    "BASE_AWARD_CENTS": 5_000_000,
    "DATE_OF_BIRTH": "1960-01-01",
    "EXPOSURE_START": "2020-01-01",
    "EXPOSURE_END": "2022-12-31",
    "DIAGNOSIS": "2021-06-15",
}

# Segregation-of-duties actor ids (PRD §2.10)
PREPARE_USER_ID = "user_approver_1"
APPROVER_USER_ID = "user_approver_2"
