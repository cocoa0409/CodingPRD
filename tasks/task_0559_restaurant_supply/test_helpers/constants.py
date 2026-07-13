"""Domain thresholds — numeric constants drawn from PRD calculations (§2.5, §3.7, §3.8, §3.9)."""

# Freight (§3.7)
PARCEL_MAX_LBS = 150
PARCEL_BASE_CENTS = 1200
PARCEL_RATE_CPL = 50            # cents per pound
LTL_BASE_CENTS = 7500
LTL_RATE_CPL = 30              # cents per pound
LIFTGATE_FEE_CENTS = 4500
FREE_FREIGHT_THRESHOLD_CENTS = 250000

# Restock refund (§3.8)
SEALED_RESTOCK_PCT = 0.15
OPENED_RESTOCK_PCT = 0.25

# Tax (§3.1, §3.4)
DEFAULT_TAX_RATE = 0.08

# Scheduling (§3.8, §3.9)
RETURN_WINDOW_DAYS = 30
INSTALL_BUFFER_MINUTES = 60

# Pagination (§2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Logical clock (§2.6)
CLOCK_START = "2026-05-01T00:00:00Z"
