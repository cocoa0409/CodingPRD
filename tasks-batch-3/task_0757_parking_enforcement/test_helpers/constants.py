"""Domain thresholds — numeric constants from the PRD calculations (PRD §3.3, §3.4, §3.8, §3.6)."""

# Repeat-offense tier multipliers (PRD §3.3)
REPEAT_TIER_0_MULT = 1.0
REPEAT_TIER_1_MULT = 1.5
REPEAT_TIER_2PLUS_MULT = 2.0

# Zone surcharges, in cents (PRD §3.3)
ZONE_SURCHARGE_DOWNTOWN_CENTS = 2000
ZONE_SURCHARGE_RESIDENTIAL_CENTS = 0
ZONE_SURCHARGE_SCHOOL_CENTS = 5000

# Fine clamp band, in cents (PRD §3.3, §3.7)
MIN_FINE_CENTS = 2500
MAX_FINE_CENTS = 25000

# Scofflaw / boot / tow thresholds (PRD §3.4)
SCOFFLAW_UNPAID_THRESHOLD = 3
BOOT_BALANCE_THRESHOLD_CENTS = 50000
TOW_BALANCE_THRESHOLD_CENTS = 100000

# Boot / tow enforcement fees and admin percentage (PRD §3.8)
BOOT_FEE_CENTS = 7500
TOW_FEE_CENTS = 15000
ADMIN_FEE_PCT = 0.085

# Room-availability buffer, in minutes (PRD §3.6)
ROOM_BUFFER_MIN = 15

# Pagination bounds (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical clock startup default (PRD §2.5)
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"
