"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Placement fee (PRD §3.6 / §3.8).
HARD_TO_FILL_MULTIPLIER = 1.20

# Relocation reimbursement gross-up (PRD §3.8).
TAX_GROSS_UP_FACTOR = 1.25

# Match-score weights (PRD §3.3).
W_SPECIALTY = 50
W_GEO = 30
W_LICENSE = 20

# Site-visit candidate travel buffer in minutes (PRD §3.4).
CANDIDATE_TRAVEL_BUFFER_MINUTES = 120

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Test-scenario defaults shared across fixtures.
TEST_DEFAULTS = {
    "CONTINGENCY_PCT": 0.20,
    "MIN_FEE_CENTS": 2_000_000,
    "GUARANTEE_DAYS": 90,
    "COMP_MIN_CENTS": 20_000_000,
    "COMP_MAX_CENTS": 30_000_000,
    "BASE_SALARY_CENTS": 24_000_000,
    "SIGN_ON_BONUS_CENTS": 2_500_000,
    "START_DATE": "2026-06-01T00:00:00Z",
    "EXPIRES_AT": "2026-05-20T00:00:00Z",
    "SITE_VISIT_START": "2026-05-03T15:00:00Z",
    "SITE_VISIT_END": "2026-05-03T16:00:00Z",
}
