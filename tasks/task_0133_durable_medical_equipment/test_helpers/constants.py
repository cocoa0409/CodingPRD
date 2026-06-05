"""Domain thresholds — numeric constants from PRD calculations and rules."""

# PRD §3.7 / §3.11 monetary and cap constants
THRESHOLDS = {
    "COVERAGE_CAP_PCT": 80,          # PRD §3.7 CMN-required non-KX coverage
    "OXY_FLOOR_CENTS": 5000,         # PRD §3.7 oxygen floor
    "OXY_CEIL_CENTS": 20000,         # PRD §3.7 oxygen ceiling
    "USED_PCT": 75,                  # PRD §3.6 used-equipment purchase rate
    "RENTAL_CAP_MONTHS": 13,         # PRD §3.7 capped-rental cap
    "RESUPPLY_WINDOW_DAYS": 90,      # PRD §3.10 CPAP resupply window
    "AUTH_VALIDITY_DAYS": 60,        # PRD §3.4 prior-auth validity
}

# Reusable test defaults
TEST_DEFAULTS = {
    "MONTHLY_RENTAL_CENTS": 10000,
    "PURCHASE_PRICE_CENTS": 100000,
}
