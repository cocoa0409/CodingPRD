"""Domain thresholds — numeric constants from PRD §2 and §3."""

# Logical clock default before any client sets it (PRD §2.4)
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # approval_valid_until = decided_at + 48 hours (PRD §3.4)
    "APPROVAL_TTL_HOURS": 48,
    # Committee quorum (PRD §3.5)
    "QUORUM": 2,
    # Exception decision window: created_at + 5 days (PRD §3.5)
    "DECISION_WINDOW_DAYS": 5,
    # Cooling-off variants (PRD §3.6)
    "COOLING_OFF_STANDARD_DAYS": 30,
    "COOLING_OFF_EXECUTIVE_DAYS": 90,
    "EARNINGS_BUFFER_DAYS": 2,
    # Attestation currency trailing window (PRD §3.1)
    "CURRENCY_WINDOW_DAYS": 365,
    # Sanction severity scoring (PRD §3.8)
    "REPEAT_BONUS": 15,
    "VALUE_BAND_HIGH": 100000,
    "VALUE_BAND_MID": 25000,
    "SCORE_CAP": 100,
    # Suspension durations (PRD §3.1/§3.8)
    "SUSPENSION_30D_DAYS": 30,
    "SUSPENSION_90D_DAYS": 90,
}

BASE_POINTS = {
    "BLACKOUT_TRADE": 40,
    "NO_PRECLEARANCE": 25,
    "RESTRICTED_LIST": 50,
    "PLAN_VIOLATION": 30,
    "OTHER": 15,
}

TEST_DEFAULTS = {
    "QUANTITY": 100,
    "PRICE": 10.00,
    "TOTAL_QUANTITY": 300,
}
