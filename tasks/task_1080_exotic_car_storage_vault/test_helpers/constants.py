"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.4, §3.9)."""

# Storage monthly fee (§3.9)
CLIMATE_SURCHARGE_CENTS = 5000
SHOWCASE_SURCHARGE_CENTS = 12000
MAX_DISCOUNT_CENTS = 20000
TIER_DISCOUNT_PCT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10, "PLATINUM": 0.20}

# Storage proration (§3.9)
PRORATION_DAYS_IN_MONTH = 30

# Service order cost (§3.9)
LABOR_RATE_CENTS = 12000
SERVICE_BASE_CENTS = {
    "DETAIL": 15000,
    "START_ENGINE": 3000,
    "CHECKOUT": 5000,
    "CHECKIN": 5000,
    "FUEL": 4000,
}

# Invoice assembly (§2.6, §3.9)
TAX_RATE = 0.08
DELIVERY_FLAT_CENTS = 25000

# Monitoring (§3.4)
BATTERY_MIN_VOLTAGE = 12.4

# Time windows (§3.7, §3.9)
OFFER_TTL_HOURS = 48
INVOICE_DUE_DAYS = 15
SUSPEND_GRACE_DAYS = 30

# Default logical-clock startup value (§1)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
