"""Domain thresholds and defaults — numeric constants from the PRD."""

# Logical clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Retention: created_at + 1825 days (PRD §2.9).
RETENTION_DAYS = 1825

# Carryover cap fraction: 20% of the active category RVO (PRD §3.5).
CARRYOVER_CAP_FRACTION = 0.20

# Verification window: 30 days after delivery (PRD §2.10).
VERIFICATION_WINDOW_DAYS = 30

# State credit energy density constant (PRD §3.7).
ENERGY_DENSITY_MJ_PER_GAL = 120.0

TEST_DEFAULTS = {
    "COMPANY_NAME": "Acme Refining",
    "YEAR": 2026,
    "PROJECTED_VOLUME_GAL": 1000,
    "STD_CELLULOSIC_PCT": 10.0,
    "STD_BIOMASS_DIESEL_PCT": 20.0,
    "STD_ADVANCED_PCT": 30.0,
    "STD_TOTAL_PCT": 40.0,
    "QUARTER_END_DATE": "2026-06-30T00:00:00Z",
    "FIELDWORK_START": "2026-09-01T00:00:00Z",
    "FIELDWORK_END": "2026-10-01T00:00:00Z",
}
