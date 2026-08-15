"""Domain thresholds — numeric constants from the PRD's calculation rules (§2.5, §3.2, §3.4, §3.7, §2.11)."""

THRESHOLDS = {
    # Screening score weights and thresholds (PRD §3.2)
    "W_NAME": 0.60,
    "W_COUNTRY": 0.25,
    "W_CITY": 0.15,
    "THRESHOLD_RESTRICTED": 0.70,
    "THRESHOLD_PROHIBITED": 0.85,
    # De minimis thresholds (PRD §3.4)
    "GROUP_E": ["CUB", "IRN", "PRK", "SYR"],
    "DE_MINIMIS_GROUP_E": 10,
    "DE_MINIMIS_DEFAULT": 25,
    # Order surcharge tiers (PRD §3.4)
    "TIER_BOUNDARY_CENTS": 100000,
    "TIER_LOW_RATE": 0.02,
    "TIER_HIGH_RATE": 0.035,
    # Per-shipment compliance fee (PRD §3.7)
    "FEE_RATE": 0.015,
    # Audit retention (PRD §2.11)
    "RETENTION_DAYS": 1825,
}

# Logical clock startup default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

TEST_DEFAULTS = {
    "UNIT_VALUE_CENTS": 1000,
    "LICENSE_VALUE_CENTS": 100000,
    "LICENSE_QUANTITY": 100,
    "VALID_FROM": "2026-07-01",
    "VALID_UNTIL": "2026-12-31",
    "TCP_EFFECTIVE_FROM": "2026-01-01",
    "TCP_EFFECTIVE_TO": "2027-01-01",
    "PLANNED_SHIP_DATE": "2026-08-10",
    "GRANT_START": "2026-08-01",
    "GRANT_END": "2026-12-01",
}
