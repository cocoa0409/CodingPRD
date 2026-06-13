"""Domain thresholds — numeric constants from the Identity Governance PRD
risk-scoring and pagination rules (§2.3, §2.7).
"""

# Risk-scoring constants (PRD §2.7).
THRESHOLDS = {
    "PRIVILEGED_STEP": 25,          # points per counted privileged entitlement
    "PRIVILEGED_CAP_STEPS": 3,      # surcharge caps at 3 privileged entitlements
    "HIGH_RISK_THRESHOLD": 100,     # effective_risk_score >= 100 flags the newest privileged grant
    "DEFAULT_RISK_WEIGHT": 10,      # entitlement risk_weight default
}

# Pagination contract (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Convenient defaults for time-gated tests.
TEST_DEFAULTS = {
    "WINDOW_START": "2026-06-01T00:00:00Z",
    "WINDOW_END": "2026-06-30T00:00:00Z",
}
