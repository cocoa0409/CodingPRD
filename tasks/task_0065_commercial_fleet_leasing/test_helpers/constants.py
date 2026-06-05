"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3.7, §3.8, §3.9)."""

# Mileage overage (PRD §3.7)
TIER1_LIMIT_MILES = 10000
TIER1_RATE_CENTS = 20
TIER2_RATE_CENTS = 35

# Excess-wear score (PRD §3.7)
WEAR_THRESHOLD = 30
EXCESS_WEAR_FLAT_CENTS = 50000

# Collision waterfall (PRD §3.8)
TOTAL_LOSS_RATIO = 0.8

# Maintenance overlap buffer (PRD §3.6)
MAINT_BUFFER_MINUTES = 60

# IFTA per-jurisdiction tax rates in dollars per gallon (PRD §3.9)
IFTA_RATE = {
    "CA": 0.40,
    "NV": 0.27,
    "AZ": 0.26,
    "OR": 0.38,
    "TX": 0.20,
    "WA": 0.49,
}
