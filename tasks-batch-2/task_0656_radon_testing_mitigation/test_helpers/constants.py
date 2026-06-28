"""Domain thresholds — numeric constants from PRD calculations.

The generic NON_EXISTENT_UUID comes from the framework. These values are the
literal constants the PRD pins for the quote, action-level, refund, and
clock-default rules.
"""

# Server-start logical clock default (PRD §1).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"

# Radon action level (PRD §2.8 / §3.3): inclusive 4.0 pCi/L boundary.
ACTION_LEVEL_PCI_L = 4.0

# Mitigation quote constants (PRD §3.4).
BASE_BY_FOUNDATION = {
    "SLAB": 150000,
    "BASEMENT": 185000,
    "CRAWLSPACE": 240000,
}
PER_SUCTION_POINT_CENTS = 45000
SUMP_SEAL_FEE_CENTS = 32000
AREA_TIER1_SQFT = 1500
AREA_TIER2_SQFT = 3000
AREA_TIER2_SURCHARGE_CENTS = 50000
AREA_TIER3_SURCHARGE_CENTS = 120000
RUSH_RATE = 0.15
DEPOSIT_RATE = 0.30

# Warranty step-tier refund bands (PRD §3.6).
STEP_T1 = 0.25
STEP_T2 = 0.50
STEP_T3 = 0.75
STEP_PCT1 = 0.90
STEP_PCT2 = 0.60
STEP_PCT3 = 0.30

# Defaults the PRD declares for optional input fields (PRD §3.2 / §3.4 / §3.7).
DEFAULT_PLACEMENT_WINDOW_HOURS = 48
DEFAULT_WARMUP_HOURS_DROPPED = 4
DEFAULT_WARRANTY_TERM_DAYS = 1825
DEFAULT_WARRANTY_GUARANTEE_CEILING_PCI_L = 2.0
DEFAULT_RETEST_INTERVAL_DAYS = 730

TEST_DEFAULTS = {
    "ADDRESS": "Test Radon Way",
    "FOUNDATION": "SLAB",
    "FLOOR_AREA_SQFT": 1400,
}
