"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Poverty guideline (PRD §3.2): 1,506,000 cents for the first household member
# plus 538,000 cents for each additional member; standard-screen cap 125.00.
POVERTY_BASE_CENTS = 1_506_000
POVERTY_PER_ADDITIONAL_CENTS = 538_000
STANDARD_CAP_PCT = 125.00

# Priority score (PRD §3.2): vulnerability step/cap, urgency tiers, score cap.
VULN_STEP = 0.15
VULN_MULT_CAP = 1.75
URGENCY_HIGH = 20
URGENCY_MED = 10
SCORE_CAP = 100.00

# Caseload weights (PRD §2.10).
EXTENDED_WEIGHT = 5
ADVICE_WEIGHT = 2

# Service-level gate (PRD §3.5): EXTENDED requires priority >= 60.00.
EXTENDED_MIN_PRIORITY = 60.00

# Temporal windows (PRD §3.3, §3.7, §3.8).
CONFLICT_VALID_DAYS = 45
REFERRAL_RESPONSE_DAYS = 10
ADVICE_ONLY_WINDOW_DAYS = 30

# Staff defaults (PRD §3.6).
DEFAULT_MAX_UNITS = 40

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "COUNTY": "CountyA",
    "GROSS_INCOME_CENTS": 1_000_000,
    "COUNTABLE_INCOME_CENTS": 900_000,
    "HOUSEHOLD_SIZE": 1,
}
