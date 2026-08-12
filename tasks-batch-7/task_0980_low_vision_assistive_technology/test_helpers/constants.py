"""Domain thresholds and constants from the PRD's calculation rules."""

# Logical clock
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Claim provisional total factors (PRD section 3.7)
VR_FACTOR_NUM = 100  # 1.00
INSURANCE_FACTOR_PCT = 80  # 0.80 coinsurance

# Payer responsibility (PRD section 3.7)
INSURANCE_COINSURANCE_PCT = 80
LOW_INCOME_SUBSIDY_HALF = 2  # client share halved for LOW_INCOME + INSURANCE

# Trial conversion fee (PRD section 3.4)
DAILY_CREDIT_PCT = 2        # 2% of list price per day used
CREDIT_CAP_PCT = 30         # credit capped at 30% of list price
SERVICE_FEE_PCT = 12        # 12% of device subtotal
TRIAL_DAYS_MIN = 1
TRIAL_DAYS_MAX = 60

# Loan agreement (PRD section 3.5)
LOAN_DURATION_DAYS = 30

# Subscription loyalty tiers (PRD section 3.8)
TIER_5_THRESHOLD_CENTS = 50000   # >= earns 5%
TIER_10_THRESHOLD_CENTS = 100000  # >= earns 10%
SUBSCRIPTION_PERIOD_DAYS = 30

# Training (PRD section 3.6)
TOTAL_SESSIONS_MIN = 1
TOTAL_SESSIONS_MAX = 20
NO_SHOW_SUSPEND_THRESHOLD = 2

# Daily sweep (PRD section 2.6)
PAST_DUE_GRACE_DAYS = 14

# Score bounds (PRD section 2.5)
SCORE_MIN = 0
SCORE_MAX = 100

TEST_DEFAULTS = {
    "DOB": "1960-01-01",
    "MAGNIFIER_PRICE": 25000,
    "CCTV_PRICE": 100000,
    "SR_MONTHLY": 25000,
    "AUTH_AMOUNT": 50000,
    "VALID_FROM": "2026-05-01T00:00:00Z",
    "VALID_UNTIL": "2026-12-31T23:59:59Z",
    "SERVICE_DATE": "2026-05-10T00:00:00Z",
}
