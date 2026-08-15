"""Domain thresholds and numeric constants from the PRD (§2.6, §3.2, §3.5)."""

# Standard contract-type tier ladder used across test setups (integer cents).
TIER_THRESHOLDS = {
    "LOW_MAX_CENTS": 100_000,
    "MID_MAX_CENTS": 500_000,
    "HIGH_MAX_CENTS": 2_000_000,
    "AUTO_APPROVE_BELOW_CENTS": 50_000,
    "REQUIRES_CHIEF_COUNSEL_ABOVE_CENTS": 10_000_000,
}

# Risk-score additive components (PRD §3.5).
RISK_SCORE = {
    "SEV_STANDARD": 0,
    "SEV_FALLBACK": 10,
    "SEV_NON_STANDARD": 30,
    "CAT_OPERATIONAL": 0,
    "CAT_COMMERCIAL": 5,
    "CAT_REGULATORY": 15,
    "CAT_RISK": 20,
    "TIER_LOW": 0,
    "TIER_MID": 5,
    "TIER_HIGH": 15,
    "TIER_VERY_HIGH": 25,
    "RISK_LOW": 0,
    "RISK_STANDARD": 5,
    "RISK_HIGH_RISK": 15,
    "ROUND_PENALTY_PER_COMPLETED_ROUND": 2,
    # Caps by clause deviation_severity_cap (PRD §3.5).
    "CAP_LOW": 30,
    "CAP_MEDIUM": 60,
    "CAP_HIGH": 100,
}

# Logical clock defaults (PRD §2.5).
CLOCK = {
    "STARTUP_UTC": "2026-08-01T00:00:00Z",
}

# Common time values used across tests.
TIMES = {
    "EFFECTIVE_DATE": "2026-09-01T00:00:00Z",
    "WINDOW_OPENS": "2026-08-01T00:00:00Z",
    "WINDOW_CLOSES": "2026-12-31T23:59:59Z",
}

TEST_DEFAULTS = {
    "CONTRACT_VALUE_CENTS": 75_000,
    "SIGNATORY_AUTHORITY_CENTS": 100_000_000,
}
