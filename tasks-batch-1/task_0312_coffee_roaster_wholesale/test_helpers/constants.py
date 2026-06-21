"""Domain thresholds — numeric constants from the Coffee Roaster Wholesale PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator: discount/shrink expressed in ten-thousandths (PRD §2.5).
BPS_DENOM = 10000

# Seconds per whole day used for freshness age computation (PRD §3.5).
SECONDS_PER_DAY = 86400

# Bounded re-roast development loop cap (PRD §3.3).
MAX_REROASTS = 2

# Minimum cupping score required to convert an approved sample (PRD §3.7).
MIN_CONVERT_SCORE = 80

# Allowed enum / domain value sets (PRD §3.2, §3.1).
ALLOWED_NET_TERMS_DAYS = [0, 15, 30, 45, 60]
ALLOWED_CADENCE_DAYS = [7, 14, 28]
ALLOWED_ROAST_LEVELS = ["LIGHT", "MEDIUM", "DARK"]

# Common test default values reused across factories/fixtures.
TEST_DEFAULTS = {
    "BASE_PRICE_CENTS_PER_KG": 2000,
    "RECEIVED_KG": 100,
    "PAR_LEVEL_KG": 10,
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "NET_TERMS_DAYS": 30,
    "FRESHNESS_WINDOW_DAYS": 60,
    "FRESHNESS_MAX_DAYS": 60,
    "EXPECTED_SHRINK_BPS": 1500,
    "CHARGE_TEMP_C": 205,
}
