"""Domain thresholds and rates stated in the PRD's calculation narratives."""

# Rates and thresholds (PRD sections 3.1, 3.6, 3.7, 3.8, 3.9, 3.10)
DEFAULT_SHARE_BPS = 7000              # marketplace default of 70 percent
CHARGEBACK_RESERVE_BPS = 500          # five percent chargeback reserve
BACKUP_WITHHOLDING_BPS = 2400         # twenty-four percent backup withholding
MIN_PAYOUT_CENTS = 5000               # fifty-dollar minimum payout
FORM_1099_THRESHOLD_CENTS = 60000     # six-hundred-dollar reporting threshold
PRICING_COOLDOWN_HOURS = 24           # spacing between plans of the same kind
REFUND_WINDOW_DAYS = 30
CHARGEBACK_REPRESENT_WINDOW_DAYS = 7
POLICY_STRIKE_SUSPEND_THRESHOLD = 3
RISK_WINDOW_DAYS = 30
REFUND_WEIGHT = 40
CHARGEBACK_WEIGHT = 40
STRIKE_WEIGHT = 20
MAX_VAT_RATE_BPS = 3000

# The logical clock reads this instant before it has ever been set.
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# Convenient instants used across the suite.
T0 = "2026-07-01T00:00:00Z"
T_AUG_1 = "2026-08-01T00:00:00Z"
T_SEP_1 = "2026-09-01T00:00:00Z"
PLAN_WINDOW_FROM = "2026-07-01T00:00:00Z"
PLAN_WINDOW_TO = "2027-07-01T00:00:00Z"

THRESHOLDS = {
    "MIN_PAYOUT_CENTS": MIN_PAYOUT_CENTS,
    "FORM_1099_THRESHOLD_CENTS": FORM_1099_THRESHOLD_CENTS,
    "POLICY_STRIKE_SUSPEND_THRESHOLD": POLICY_STRIKE_SUSPEND_THRESHOLD,
}

TEST_DEFAULTS = {
    "CURRENCY": "USD",
    "COUNTRY": "US",
    "PRICE_CENTS": 10000,
}
