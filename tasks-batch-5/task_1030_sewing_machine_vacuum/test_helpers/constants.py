"""Domain thresholds and rates from the PRD calculations (§2.6, §3.2-§3.8)."""

# Trade-in appraisal schedule and band (PRD §3.3).
TRADE_IN_SCHEDULE = {"GOOD": 40000, "FAIR": 25000, "POOR": 10000}
TRADE_IN_BAND = 15000

# Repair invoicing (PRD §3.4).
LABOR_RATE_CENTS = 9000  # $90.00 / hour

# Sales pricing (PRD §3.3).
TAX_RATE = 0.08
DISCOUNT_PCT = {"STANDARD": 0.0, "GOLD": 0.05, "PLATINUM": 0.10}

# Loyalty tiers (PRD §3.2).
GOLD_THRESHOLD_CENTS = 500000
PLATINUM_THRESHOLD_CENTS = 1500000

# Subscription period (PRD §3.7).
PERIOD_DAYS = 30

# Rental late fee (PRD §3.5).
LATE_MULTIPLIER = 1.5

# Class scheduling buffer (PRD §3.6).
SCHEDULE_BUFFER_MINUTES = 30

# Default clock at server startup before any /_clock call (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-07-01T00:00:00Z"
