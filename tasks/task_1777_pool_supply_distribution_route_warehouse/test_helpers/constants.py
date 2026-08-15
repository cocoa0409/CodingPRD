"""Domain thresholds — numeric constants from PRD §2.11, §3.5, §3.8, §3.9."""

# Account tier ledger thresholds (PRD §2.11)
TIER_ELITE_CENTS = 2_000_000      # $20,000 -> ELITE (inclusive)
TIER_PREMIER_CENTS = 5_000_000    # $50,000 -> PREMIER (inclusive)

# Tier discount factors applied at order confirmation (PRD §3.5)
TIER_DISCOUNT = {"PRO": 0.00, "ELITE": 0.05, "PREMIER": 0.10}

# Freight program (PRD §3.5)
FREIGHT_FREE_MIN_CENTS = 50_000        # $500 free-freight minimum (order-level)
FREIGHT_BASE_CENTS = 2_500
FREIGHT_HAZMAT_SURCHARGE_CENTS = 1_800
FREIGHT_SHORTFALL_CAP_CENTS = 7_500

# Warranty labor credit (PRD §3.8)
FLAT_LABOR_HOURS = 2        # provisional credit hours at submit
LABOR_CAP_HOURS = 6         # final credit cap in hours
MAX_INFO_CYCLES = 3         # MORE_INFO loop limit

# Returns (PRD §3.9)
RESTOCK_PCT = 0.15          # OVERSTOCK restocking fee

# Defaults
DEFAULT_WILLCALL_CUTOFF_MINUTES = 90
DEFAULT_SHORTAGE_FREEZE_THRESHOLD = 100
DEFAULT_LOW_STOCK_FLOOR = 0

# Logical clock (PRD §2.6): server startup default
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_PICKUP_SLOT = "2026-08-01T13:00:00Z"
DEFAULT_ROUTE_DATE = "2026-08-10"
