"""Domain thresholds and numeric constants named in the PRD."""

# Loyalty points (PRD sections 2.9, 3.x)
POINT_VALUE_CENTS = 0.5                 # each redeemed point is worth half a cent
DEFAULT_STACK_CAP_POINTS = 500          # member stack_cap_points default
POINTS_PER_DOLLAR_FUEL = 0.5
POINTS_PER_DOLLAR_STORE = 1.0
POINTS_PER_DOLLAR_SERVICE = 1.0
POINTS_PER_DOLLAR_PARKING = 1.0
POINTS_EXPIRY_DAYS = 360

# Contract quoting (PRD section 3.2)
FREIGHT_PER_GALLON = 0.1500             # $/gal freight allowance
TIER_DISCOUNT_PER_GALLON = {"T1": 0.02, "T2": 0.05, "T3": 0.09}

# Fleet rolling-tier breakpoints (PRD section 3.3)
TIER_T2_THRESHOLD_GAL = 5000
TIER_T3_THRESHOLD_GAL = 20000

# Parking (PRD section 3.5)
PARKING_RATE_PER_HOUR_CENTS = 300
OVERSIZE_FEE_CENTS = 800
PARKING_GRACE_MINUTES = 15
PARKING_MAX_WINDOW_HOURS = 336
PARKING_NO_SHOW_GRACE_HOURS = 2

# Service queue pricing (PRD section 3.5)
SHOWER_BASE_CENTS = 1500
LAUNDRY_BASE_CENTS = 400
WEEKEND_SURCHARGE_CENTS = 300
PEAK_SURCHARGE_CENTS = 150
PREEMPTION_MIN_ELAPSED_MINUTES = 15

# Water metering (PRD section 3.5)
SHOWER_CAP_MINUTES = 45
SHOWER_GPM = 2.5
LAUNDRY_GAL_PER_LB = 2.0

# Scale fees (PRD section 3.5)
FIRST_WEIGH_FEE_CENTS = 1250
CERTIFIED_FEE_CENTS = 400
REWEIGH_FEE_CENTS = 0

# Shift cash control (PRD sections 2.8, 3.8)
DROP_TRIGGER_FLOAT_MULTIPLE = 5
LOW_FLOAT_MULTIPLE = 1
VARIANCE_TOLERANCE_CENTS = 500
DENOMINATIONS_CENTS = [10000, 5000, 2000, 1000, 500, 100, 25, 10, 5, 1]

# Shop invoice (PRD section 3.7)
ENV_FEE_PER_TIRE_CENTS = 150
SHOP_SUPPLIES_PCT = 0.03

# Bulk supply (PRD section 3.9)
TARGET_FILL_PCT = 0.90
WATER_BOTTOM_MAX_INCHES = 1.0

# Logical clock anchors used across tests
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"   # server default before any set call
TEST_CLOCK_ISO = "2026-08-12T10:00:00Z"      # Wednesday, off-peak

# Common fixture money
REGISTER_FLOAT_CENTS = 20000
