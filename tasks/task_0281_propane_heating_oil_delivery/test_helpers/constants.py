"""Domain thresholds — numeric constants from the PRD calculations (§3).

NON_EXISTENT_UUID comes from the framework.
"""

# Reorder projection (§3.3): k_factor is in milli-gallons per HDD; divide by 1000.
K_FACTOR_SCALE = 1000

# Budget plan (§3.10): twelve installments per year.
MONTHS_PER_YEAR = 12

# Delivery price volume tiers and floor (§3.2).
VOL_TIER1_GALLONS = 150
VOL_TIER1_DISCOUNT_CENTS = 5
VOL_TIER2_GALLONS = 300
VOL_TIER2_DISCOUNT_CENTS = 12
MIN_FLOOR_CENTS = 50

# Invoice total surcharges (§3.6).
EMERGENCY_SURCHARGE_PCT = 10
OFF_ROUTE_FEE_CENTS = 2500

# Tank defaults (§3.3).
DEFAULT_REORDER_THRESHOLD_PCT = 30
DEFAULT_DELIVERY_MODE = "WILL_CALL"
DEFAULT_MONITOR_INSTALLED = False

# Truck default (§3.5).
DEFAULT_TURNAROUND_BUFFER_MINUTES = 60

# Pagination defaults (§2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
