"""Domain thresholds — numeric constants from the Estate Sale PRD calculations."""

# Tiered commission (PRD §3.8)
TIER1_THRESHOLD_CENTS = 500000
TIER1_RATE = 0.40
TIER2_RATE = 0.30

# Card processing fee (PRD §3.4 / §3.8)
CARD_FEE_RATE = 0.029

# Sale-window / booking guards (PRD §3.3, §3.7)
SALE_WINDOW_MAX_DAYS = 4
TRUCK_BUFFER_MINUTES = 60

# Markdown schedule defaults (PRD §3.4)
DEFAULT_MARKDOWN_DAY1_PCT = 0.25
DEFAULT_MARKDOWN_DAY2_PCT = 0.50
DEFAULT_MARKDOWN_DAY3PLUS_PCT = 0.75

# Project defaults (PRD §3.1)
DEFAULT_MIN_COMMISSION_CENTS = 50000

# Logical clock (PRD §2.6)
STARTUP_CLOCK = "2026-05-01T00:00:00Z"

SECONDS_PER_DAY = 86400
