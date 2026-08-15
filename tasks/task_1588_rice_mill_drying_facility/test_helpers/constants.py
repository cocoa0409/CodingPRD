"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Drying model (PRD §3.3/§3.4)
BASE_MOISTURE_PCT = 13.0
SHRINK_SPAN = 87.0  # 100 - 13.0 base
HANDLING_LOSS_PCT = 0.5

# Tiered drying charge (PRD §3.4)
TIER1_MAX_POINTS = 3.0
TIER1_CENTS = 4
TIER2_MAX_POINTS = 3.0
TIER2_CENTS = 7
TIER3_CENTS = 12

# Grade determination (PRD §3.4)
W_FOREIGN_MATTER = 2
W_DAMAGE = 3
W_BROKEN = 1
GRADE_THRESHOLDS = [
    (2.0, "US_NO_1"),
    (5.0, "US_NO_2"),
    (10.0, "US_NO_3"),
    (15.0, "US_NO_4"),
    (20.0, "US_NO_5"),
]

# Contract fulfillment (PRD §3.2/§3.4)
OVERDELIVERY_TOLERANCE_PCT = 5.0

# Settlement (PRD §3.8)
CHECKOFF_RATE = 0.005

# Milling standards (PRD §3.6)
TOTAL_RICE_PCT = {"LONG_GRAIN": 0.68, "MEDIUM_GRAIN": 0.72}
HEAD_RATIO = {"LONG_GRAIN": 0.60, "MEDIUM_GRAIN": 0.66}
BREWERS_PCT = 0.05
BRAN_PCT = 0.08
LOSS_PCT = 0.02

# Packaging (PRD §3.6)
CHANGEOVER_MINUTES = 30
LBS_PER_KG = 2.20462262

# Season logical clock (PRD §2.4)
SEASON_CLOCK_START = "2026-08-01T00:00:00Z"

# Common scenario values
SEASON_WINDOW = ("2026-08-01", "2026-10-31")
SETTLEMENT_PERIOD = ("2026-08-01", "2026-08-31")
DEFAULT_SPOT_PRICE_CENTS = 1300
DEFAULT_BIN_CAPACITY_CWT = 500.00
DEFAULT_SPOT_DAILY_CAP = 2
