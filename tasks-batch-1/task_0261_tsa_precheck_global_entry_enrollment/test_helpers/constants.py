"""Domain thresholds — numeric constants from the PRD's calculations."""

# Risk-scoring weights (PRD §3.3): criminal x15, watchlist x60, revocation x25.
RISK_WEIGHTS = {
    "W_CRIMINAL": 15,
    "W_WATCHLIST": 60,
    "W_REVOCATION": 25,
}

# Risk score is clamped to the inclusive range [0, 100] (PRD §2.8, §3.3).
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

# Renewal fee discount (PRD §3.2): 20% off base, round-half-up.
RENEWAL_DISCOUNT_RATE = 0.20

# Processing fee retained on partial refund (PRD §3.8).
PROCESSING_FEE_CENTS = 1175

# Default program configuration used across fixtures.
TEST_DEFAULTS = {
    "BASE_FEE_CENTS": 7800,
    "VALIDITY_YEARS": 5,
    "VETTING_RISK_THRESHOLD": 40,
    "VETTING_DENY_THRESHOLD": 70,
    "REDRESS_MIN_SCORE": 30,
    "RENEWAL_WINDOW_DAYS": 180,
}

# A fixed clock instant used to make time-dependent tests deterministic.
DEFAULT_CLOCK = "2026-06-09T12:00:00Z"
