"""Domain thresholds — numeric constants drawn from the PRD's calculation rules (§3)."""

# Pier pricing (§3.3)
PIER_TIER1_CENTS = 120_000       # depth < 15 ft
PIER_TIER2_CENTS = 165_000       # 15 ft <= depth < 25 ft (15 is inclusive to tier 2)
PIER_TIER3_CENTS = 210_000       # depth >= 25 ft
ANCHOR_UNIT_CENTS = 45_000

SOIL_MULT = {"STABLE": 1.00, "EXPANSIVE": 1.15, "UNSTABLE": 1.30}
ACCESS_MULT = {"EASY": 1.00, "MODERATE": 1.10, "HARD": 1.25}

PIER_TOLERANCE = 2               # |piers_installed - pier_count| must be <= 2 at complete

# Financing (§3.3 / §3.4)
VOLUME_DISCOUNT_THRESHOLD_CENTS = 2_000_000
VOLUME_DISCOUNT_RATE = 0.05
PLAN_FEE_RATE = {"CASH": 0.00, "PLAN_12": 0.05, "PLAN_60": 0.12}
FINANCING_LIMIT_CENTS = 5_000_000

# Claim settlement (§3.8)
INCHES_PER_PIER = 0.5
REMEDIATION_PIER_CENTS = 150_000
MISSED_PENALTY = 0.10
COVERAGE_FLOOR = 0.50

# Named durations, all measured against the logical clock (§3.3 / §3.6 / §3.7)
QUOTE_VALID_DAYS = 30
VISIT_INTERVAL_DAYS = 365
MIN_VISIT_GAP_DAYS = 300

# The server's logical clock startup default (§2.5).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
