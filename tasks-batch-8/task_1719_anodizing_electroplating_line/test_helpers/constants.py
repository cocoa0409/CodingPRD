"""Domain thresholds — numeric constants from PRD calculations."""

# Equivalent weights per chemistry family (PRD §3.2)
EQ_WEIGHTS = {
    "SULFURIC": 49.0,
    "CHROMIC": 33.3,
    "NICKEL": 29.35,
    "ZINC": 32.69,
    "COPPER": 31.77,
    "CYANIDE": 49.0,
}

# Dragout depletion rate: g/L depleted per dm^2 of load surface area (PRD §3.5)
DRAGOUT_RATE = 0.0008

# Pricing constants (PRD §3.4)
MASKING_RATE_CENTS_PER_MIN = 85
BARREL_FLAT_FEE_CENTS = 1200
UNASSIGNED_RACK_FEE_CENTS = 2000
REWORK_RATE = 0.20
HAZMAT_FEE_CENTS = 2500

# Thickness tier rates (cents per dm^2-um) (PRD §3.4 step 4)
TIER_RATE_LOW = 12      # billing thickness < 10 um
TIER_RATE_MID = 15      # 10 <= billing thickness < 25 um
TIER_RATE_HIGH = 19     # billing thickness >= 25 um

# Discount tier thresholds keyed on pre-discount subtotal (cents) (PRD §3.4 step 7)
DISCOUNT_THRESHOLD_HIGH = 1_000_000
DISCOUNT_THRESHOLD_MID = 500_000
DISCOUNT_RATE_HIGH = 0.08
DISCOUNT_RATE_MID = 0.05

# Waste densities (kg/L) (PRD §3.9)
DENSITY_BATH_DUMP = 1.2
DENSITY_SLUDGE_PRESS = 1.5
DENSITY_RINSE_CONCENTRATE = 1.2

# Max completed strip-and-replate cycles (PRD §3.6)
MAX_REWORKS = 2

# Cancellation fee fraction on the processing line for late manager cancel (PRD §3.7)
LATE_CANCEL_FEE_FRACTION = 0.5

# Logical clock startup default (PRD §2.6)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
