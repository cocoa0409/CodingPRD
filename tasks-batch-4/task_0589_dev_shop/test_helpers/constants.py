"""Domain thresholds — numeric constants drawn from the PRD narrative."""

# Budget posture thresholds on the 4-decimal burn_ratio; both inclusive (PRD 3.5).
AT_RISK_THRESHOLD = 0.90
OVERBURNED_THRESHOLD = 1.00

# Change-request quoting (PRD 3.6).
CR_QUOTE = {
    "TIER1_FLOOR": 5000.00,
    "TIER1_DISCOUNT": 0.05,
    "TIER2_FLOOR": 20000.00,
    "TIER2_DISCOUNT": 0.10,
    "PM_OVERHEAD_PCT": 0.12,
    "RUSH_PCT": 0.15,
}
MAX_CR_REVISION_ROUNDS = 2

# Invoicing (PRD 3.8).
TAX_RATE = 0.0825

# Support SLA (PRD 3.9). Minutes; breach uses a strict `>` comparison.
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17
SLA_RESPONSE_MINUTES = {"SEV1": 60, "SEV2": 240, "SEV3": 480}
SLA_RESOLUTION_MINUTES = {"SEV1": 480, "SEV2": 1440, "SEV3": 2880}
TIER_CREDIT_PCT = {"GOLD": 0.10, "SILVER": 0.05, "BRONZE": 0.02}
CREDIT_CAP_PCT = 0.25
RETAINER_COOLDOWN_DAYS = 7

# Time-logging caps (PRD 3.4).
MAX_HOURS_PER_ENTRY = 12
DAILY_HOURS_CAP = 12

# Pagination (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Logical-clock startup default (PRD 2.4).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Values reused across setups.
TEST_DEFAULTS = {
    "CONTRACT_VALUE": 100000.00,
    "BUDGET_HOURS_CAP": 500,
    "HOURLY_RATE": 200.00,
    "SPRINT_START": "2026-05-04",
    "SPRINT_END": "2026-05-18",
    "WORK_DATE": "2026-05-05",
    "MONTHLY_FEE": 4000.00,
}
