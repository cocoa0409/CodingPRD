"""Domain thresholds — numeric constants from the PRD fee and scoring rules
(PRD sections 3.12, 3.13). NON_EXISTENT_UUID comes from the framework.
"""

# Fee composition constants (PRD section 3.12).
FEE = {
    "BASE_FEE_CENTS": 7500,
    "PER_PAGE_CENTS": 25,
    "RUSH_FEE_CENTS": 5000,
    "SKIP_TRACE_FEE_CENTS": 9000,
    "FREE_ATTEMPTS": 1,
    "TIER1_MAX": 3,
    "ATTEMPT_RATE1_CENTS": 2500,
    "ATTEMPT_RATE2_CENTS": 4000,
    "STAKEOUT_FEE_CENTS": 12000,
    "RUSH_LABOR_MULT": 1.5,
}

# Reliability scoring weights (PRD section 3.13).
RELIABILITY = {
    "W_SERVED": 1.0,
    "W_NONEST": 0.5,
    "DEFAULT_SCORE": 100,
}

# County policy defaults (PRD section 3.1).
COUNTY_DEFAULTS = {
    "E_FILE_ENABLED": False,
    "MIN_DILIGENT_ATTEMPTS": 3,
    "FILING_FEE_CENTS": 4000,
    "MAX_CONCURRENT_FILINGS": 2,
}

# Server default capacity (PRD section 3.1).
SERVER_DEFAULTS = {
    "MAX_ACTIVE_ASSIGNMENTS": 5,
}

# A syntactically valid UUID that resolves to nothing (for 404 tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Default logical clock at server startup (PRD section 2.8).
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"
