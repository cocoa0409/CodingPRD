"""Domain thresholds — numeric constants from the PRD's calculations and limits."""

# Default logical-clock startup instant (PRD 2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Production loss accounting (PRD 2.11 / 3.7).
STANDARD_PLUG_COST_CENTS = 35

# Volume rebate tiers (PRD 3.10).
REBATE_TIER_1_UNITS = 2000
REBATE_TIER_1_PCT = 0.02
REBATE_TIER_2_UNITS = 5000
REBATE_TIER_2_PCT = 0.05

# Freight schedule (PRD 3.10).
RACK_CAPACITY = 50
FREIGHT_BASE_CENTS = {"IN_STATE": 2500, "NEIGHBOR": 4000, "FAR": 7000}
FREIGHT_PER_RACK_CENTS = {"IN_STATE": 600, "NEIGHBOR": 1100, "FAR": 1900}
FREIGHT_FLOOR_CENTS = {"IN_STATE": 2500, "NEIGHBOR": 4000, "FAR": 7000}
FREIGHT_CAP_CENTS = {"IN_STATE": 9000, "NEIGHBOR": 16000, "FAR": 28000}
ORIGIN_STATE = "OR"
NEIGHBOR_CODES = ["WA", "CA", "ID", "NV"]

# Zone fill posture (PRD 2.10).
TIGHT_FRACTION = 0.15

# Batch shrink / scouting auto-cull threshold (PRD 3.5).
AUTO_CULL_PCT = 0.50

# Pagination defaults (PRD 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
