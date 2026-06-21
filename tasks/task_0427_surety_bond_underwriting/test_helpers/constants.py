"""Domain thresholds — numeric constants from PRD calculations (§3.2, §3.3, §3.5)."""

# Credit-tier derivation (PRD §3.2): boundaries inclusive (>=).
CREDIT_TIER = {
    "PREFERRED_MIN_SCORE": 720,
    "STANDARD_MIN_SCORE": 620,
}

# Premium rating rate table (PRD §3.3), in basis points: RATE_TABLE[credit_tier][bond_type].
RATE_TABLE = {
    "PREFERRED": {"BID": 100, "PERFORMANCE": 150, "PAYMENT": 150, "LICENSE_PERMIT": 80, "FIDELITY": 120},
    "STANDARD": {"BID": 150, "PERFORMANCE": 225, "PAYMENT": 225, "LICENSE_PERMIT": 120, "FIDELITY": 180},
    "SUBSTANDARD": {"BID": 250, "PERFORMANCE": 375, "PAYMENT": 375, "LICENSE_PERMIT": 200, "FIDELITY": 300},
}

# Premium rating constants (PRD §3.3).
LARGE_RISK_SURCHARGE_BPS = 50
MAX_RATE_BPS = 400

# Earned-premium short-rate penalty (PRD §3.5): ten percent of the unearned portion.
SHORT_RATE_PENALTY_PCT = 0.10

# Credit score input range (PRD §2.12 / §3.2): 300 to 850 inclusive.
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850

# Default logical clock value before any clock call (PRD §2.10).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# Common penal-sum and limit defaults reused across fixtures.
TEST_DEFAULTS = {
    "SINGLE_LIMIT": 20_000_000,
    "AGGREGATE_LIMIT": 50_000_000,
    "REFERRAL_THRESHOLD": 25_000_000,
    "LOSS_ALERT_THRESHOLD": 50_000_000,
    "TERM_MONTHS": 12,
}
