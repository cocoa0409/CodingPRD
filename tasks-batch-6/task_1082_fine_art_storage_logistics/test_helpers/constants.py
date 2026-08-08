"""Domain thresholds — numeric constants from the PRD calculations."""

# Storage fee (Section 3.2)
DAILY_RATE_BY_CLIMATE = {"AMBIENT": 500, "COOL": 800, "COLD": 1200}
SIZE_MULT = {"SMALL": 1.0, "MEDIUM": 1.5, "LARGE": 2.0}

# Insurance premium (Section 3.5)
COVERAGE_MULT = {"STORAGE_ONLY": 1.0, "TRANSIT": 1.5, "ALL_RISK": 2.0}
FRAGILITY_MULT = {"LOW": 1.0, "MEDIUM": 1.25, "HIGH": 1.5}
MIN_PREMIUM_CENTS = 5000

# Transport charge (Section 3.4)
CREW_HOURLY_CENTS = 9000
RIGGING_SURCHARGE_CENTS = 25000

# Invoicing (Section 3.8)
TAX_RATE = 0.0875

# Temporal windowing (Section 2.9)
SETUP_BUFFER_MINUTES = 60

# Defaults
DEFAULT_CREDIT_TERMS_DAYS = 30
CLOCK_STARTUP = "2026-05-01T00:00:00Z"
