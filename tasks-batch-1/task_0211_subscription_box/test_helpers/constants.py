"""Domain thresholds — numeric constants from PRD calculations.

NON_EXISTENT_UUID comes from the framework (re-exported via the barrel).
"""

# Win-back loyalty credit constants (PRD §3.7).
WINBACK = {
    "BASE_GRANT_PCT": 0.20,
    "TENURE_WEIGHT": 0.05,
    "TENURE_CAP": 6,
    "MAX_GRANT_CENTS": 5000,
}

# Win-back window length (PRD §3.3): half-open [cancelled_at, cancelled_at + 60 days).
WINBACK_WINDOW_DAYS = 60

# Pause ceiling per 12-period term (PRD §3.3): the third existing pause is the
# last permitted; a further request once the count has reached 3 is rejected.
PAUSE_LIMIT = 3

# Default test values reused across fixtures.
TEST_DEFAULTS = {
    "PERIOD_PRICE_CENTS": 6000,
    "BOX_ITEM_COUNT": 1,
    "WAVE_CAPACITY": 10,
}
