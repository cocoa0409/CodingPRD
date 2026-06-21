"""Domain thresholds — numeric constants from PRD calculations and §3 prose.

All monetary values are integer cents.
"""

# Risk-score weights by complaint category (PRD §3.8).
CATEGORY_WEIGHT = {
    "FRAUD": 40,
    "FEE_OVERCHARGE": 20,
    "RECORDKEEPING": 15,
    "OTHER": 10,
}

# Suspension threshold and score ceiling (PRD §3.8 / §3.9).
RISK_SUSPEND_THRESHOLD = 50
SCORE_CEILING = 100

# Allowed commission term lengths in months (PRD §3.1).
COMMISSION_TERM_MONTHS_ALLOWED = [48, 60, 96, 120]

# Test default values reused across fixtures.
TEST_DEFAULTS = {
    "BOND_MINIMUM_CENTS": 500_000,
    "BOND_FACE_VALUE_CENTS": 1_000_000,
    "COMMISSION_TERM_MONTHS": 48,
    "RENEWAL_GRACE_DAYS": 30,
    "SESSION_ACT_FEE_CAP_CENTS": 1_200,
    "RON_SURCHARGE_CAP_CENTS": 2_500,
}
