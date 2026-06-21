"""Domain thresholds — numeric constants from PRD calculations (§3.5, §3.4, §3.8)."""

# Use tax (§3.5)
STATE_USE_TAX_RATE = 0.065
COUNTY_RATE = {
    "KING": 0.025,
    "PIERCE": 0.014,
    "DEFAULT": 0.010,
}
TRANSFER_USE_TAX_CAP_CENTS = 150000

# Registration fee — depreciation schedule + weight fee (§3.5)
CURRENT_REG_YEAR = 2026
DEP_RATE_NEW = 0.0110
DEP_RATE_BAND_1 = 0.0090
DEP_RATE_BAND_2 = 0.0060
DEP_RATE_BAND_3 = 0.0030
WEIGHT_FEE = {
    "PASSENGER": 4300,
    "TRUCK": 9000,
    "MOTORCYCLE": 2500,
}

# REAL ID surcharge (§3.5)
REAL_ID_SURCHARGE_CENTS = 3000

# Temporal windows (§3.4, §3.5, §3.8)
EMISSIONS_VALID_DAYS = 365
REGISTRATION_TERM_DAYS = 365

# Default clock instant used by time-window fixtures.
DEFAULT_CLOCK_ISO = "2026-06-01T00:00:00Z"
