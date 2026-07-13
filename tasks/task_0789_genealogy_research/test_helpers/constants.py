"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Project cost (§3.2): overage rate is 8000 cents per whole overage hour.
OVERAGE_RATE_CENTS = 8000

# Hours cap (§3.2): consumed_hours + new billable hours must not exceed
# budget_hours * 1.5 (hard cap).
MAX_OVERAGE_MULTIPLIER = 1.5

# Person confidence (§3.4): quality weights, divisor, gate.
CITATION_WEIGHT = {"PRIMARY": 3, "SECONDARY": 2, "INDIRECT": 1}
CONFIDENCE_DIVISOR = 6
CONFIDENCE_GATE = 0.75
MIN_VERIFIED_CITATIONS = 2

# Milestone invoicing (§3.9).
TIER_DISCOUNT = {"STANDARD": 0.00, "PREMIUM": 0.10}
RUSH_SURCHARGE_CENTS = 5000
PRICE_CAP_MULTIPLIER = 1.5
AGENCY_FEE_PCT = 0.075

# DNA predicted relationship bands (§3.5), inclusive lower bounds.
DNA_BANDS = {
    "PARENT_CHILD": 3400,
    "FULL_SIBLING": 2000,
    "CLOSE_FAMILY": 1300,
    "COUSIN": 200,
}

# Repository scheduling (§3.6).
RESEARCHER_BUFFER_MINUTES = 30

# Entity defaults.
DEFAULT_ADDON_FEE_CENTS = 15000
DEFAULT_CONCURRENT_CAPACITY = 2

# Server logical clock startup default (§2.8).
CLOCK_STARTUP_UTC = "2026-03-01T00:00:00Z"
