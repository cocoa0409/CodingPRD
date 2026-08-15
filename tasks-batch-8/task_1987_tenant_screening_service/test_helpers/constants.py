"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Identity verification (PRD §3.2)
    "IDENTITY_PASS_THRESHOLD": 70,
    "MAX_IDENTITY_ATTEMPTS": 3,
    # Screening fee (PRD §3.4)
    "BASE_FEE_CENTS": 2500,
    "SURCHARGE_RATE": 0.125,
    "PER_TYPE_SURCHARGE_CENTS": 313,  # round_half_up(0.125 * 2500)
    "PORTABLE_FLAT_FEE_CENTS": 1000,
    # Suppression defaults (PRD §3.4)
    "CRIMINAL_LOOKBACK_DEFAULT": 7,
    "EVICTION_LOOKBACK_DEFAULT": 7,
    # Compliance windows (PRD §3.3, §3.8, §3.9)
    "DISPUTE_WINDOW_DAYS": 30,
    "REINVESTIGATION_SLA_DAYS": 30,
    "PORTABLE_VALIDITY_DAYS": 30,
}

TEST_DEFAULTS = {
    "RENT_CENTS": 200000,
    "INCOME_CENTS": 600000,
    "CREDIT_SCORE": 700,
    "MIN_CREDIT_SCORE": 650,
    "INCOME_MULTIPLIER": 3.0,
    "GUARANTOR_INCOME_MULTIPLIER": 4.0,
    # Three-type search fee (PRD §3.4): 2500 + 313 + 313 + 313
    "FULL_SEARCH_FEE_CENTS": 3439,
    # Two-type search fee (criminal prohibited): 2500 + 313 + 313
    "NO_CRIMINAL_SEARCH_FEE_CENTS": 3126,
}

# Canonical logical-clock instants used across scenarios.
CLOCKS = {
    "START": "2026-08-01T00:00:00Z",
    "CONSENT": "2026-08-05T10:30:00Z",
    "PORTABLE_DAY30": "2026-08-31T00:00:00Z",
    "PORTABLE_DAY31": "2026-09-01T00:00:00Z",
    "AFTER_DISPUTE_WINDOW": "2026-09-15T00:00:00Z",
}

# Standard criteria window covering the 2026-08-01 default clock.
CRITERIA_WINDOW = {
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2026-12-31T00:00:00Z",
}
