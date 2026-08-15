"""Domain thresholds — numeric constants from PRD §2–§3."""

# Logical clock startup default (PRD §2.5): before any operator intervention the
# clock starts at exactly this instant and never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Decision deadline variants (PRD §3.5)
    "DECISION_CUTOFF_TIME": "14:00:00Z",
    "SAME_DAY_DEADLINE_TIME": "20:00:00Z",
    "MAX_EXTENSION_HOURS": 24,
    # Fees (PRD §3.7)
    "PROVISIONAL_EXCEPTION_FEE_CENTS": 200,
    "RETURN_FEE_CENTS": 500,
    "MONTHLY_MINIMUM_CENTS": 5000,
    "TIER1_LIMIT": 10,
    "TIER2_LIMIT": 40,
    "TIER1_FEE_CENTS": 200,
    "TIER2_FEE_CENTS": 150,
    "TIER3_FEE_CENTS": 100,
    # Liability (PRD §3.8)
    "PROVISIONAL_CREDIT_CAP_CENTS": 25000,
    "SOD_CASE_THRESHOLD_CENTS": 25000,
    "CLAIM_WINDOW_DAYS": 30,
    # Waiver authority (PRD §3.7)
    "WAIVER_CAP_BANKOPS_CENTS": 1000,
    # Reverse-tier volume gate (PRD §3.1)
    "REVERSE_VOLUME_MAX_90D": 75,
    "REVERSE_WINDOW_DAYS": 90,
    # Training buffer (PRD §3.1)
    "TRAINING_BUFFER_MINUTES": 30,
}

# Server-side defaults applied at enrollment creation (PRD §3.1).
TEST_DEFAULTS = {
    "DEADLINE_MODE": "SAME_DAY_CUTOFF",
    "DECISION_WINDOW_HOURS": 24,
    "AMOUNT_TOLERANCE_CENTS": 0,
    "PAYEE_SCORE_THRESHOLD": 85,
    "STALE_DAYS": 180,
}
