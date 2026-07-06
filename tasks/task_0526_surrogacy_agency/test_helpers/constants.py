"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Carrier experience-bonus tiers (PRD §3.3).
TIER1_PCT = 0.05          # prior_deliveries 2-3
TIER2_PCT = 0.10          # prior_deliveries >= 4
MULTIPLES_ADDON_CENTS = 500_000

# Insurance gap-premium (PRD §3.2).
GAP_RATE_PER_MONTH = 0.015
GAP_MONTHS = 9

# Contract cooling-off (PRD §3.4).
COOLING_OFF_DAYS = 3

# Parentage-hostile jurisdictions (PRD §3.6).
PARENTAGE_HOSTILE_STATES = {"LA", "NE"}

# Pagination (PRD §2.3).
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100

# Logical-clock startup default (PRD §2.11).
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "IP_BUDGET_CENTS": 6_000_000,
    "CARRIER_BASE_COMP_CENTS": 4_000_000,
    "DONOR_COMP_CENTS": 800_000,
    "PROPOSED_CARRIER_COMP_CENTS": 4_000_000,
}
