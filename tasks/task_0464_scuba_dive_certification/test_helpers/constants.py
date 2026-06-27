"""Domain thresholds — numeric constants from PRD calculations and gates.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Instructor-ratio capacity (PRD 3.4)
POOL_BASE_RATIO = 8
POOL_ASSISTANT_BONUS = 4
OW_BASE_RATIO = 4
OW_ASSISTANT_BONUS = 2

# Fill price (PRD 3.9)
AIR_BASE_CENTS = 1200
NITROX_SURCHARGE_LOW = 800     # o2_pct <= 32
NITROX_SURCHARGE_MID = 1400    # 33..36
NITROX_SURCHARGE_HIGH = 2200   # 37..40
LARGE_TANK_THRESHOLD_L = 12    # > 12 applies the large-tank factor
LARGE_TANK_FACTOR = 1.25

# Trip booking total (PRD 3.7)
GROUP_DISCOUNT_MIN_PARTY = 4
GROUP_DISCOUNT_PCT = 0.15
DEPOSIT_PCT = 0.30

# Enrollment completion (PRD 3.3)
EL_WEIGHT = 0.2
POOL_WEIGHT = 0.3
OW_WEIGHT = 0.5

# Rental charge / settlement (PRD 3.8)
LATE_MULTIPLIER = 1.5

# Waiver expiry (PRD 3.1)
WAIVER_VALID_DAYS = 365

# Gear service due (PRD 3.9)
VIP_INTERVAL_DAYS = 365
HYDRO_INTERVAL_DAYS = 1825

# Logical clock startup default (PRD 2.4)
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"
