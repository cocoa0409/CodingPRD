"""Domain thresholds — numeric constants from PRD calculations (§3.6–§3.8)."""

# Surge multiplier calculation (§3.6)
RUSH_HOUR_STEP = 0.50
MULTIPLIER_CAP = 2.50

# Heat Map bands (§3.6), lower-inclusive / upper-exclusive
HEAT_COOL_MAX_EXCLUSIVE = 1.25   # m < 1.25 -> COOL
HEAT_WARM_MAX_EXCLUSIVE = 1.75   # 1.25 <= m < 1.75 -> WARM
HEAT_HOT_MAX_EXCLUSIVE = 2.50    # 1.75 <= m < 2.50 -> HOT; m >= 2.50 -> BLAZING

# Ratio bands (§3.6), lower-inclusive
RATIO_BAND_1_MAX = 1.00          # ratio < 1.00 -> raw 1.00
RATIO_BAND_2_MAX = 2.00          # 1.00 <= ratio < 2.00 -> raw 1.50
RATIO_BAND_3_MAX = 3.00          # 2.00 <= ratio < 3.00 -> raw 2.00; ratio >= 3.00 -> raw 2.50

# Fare / payout (§3.7–§3.8)
BOOKING_FEE_CENTS = 150
DRIVER_SHARE = 0.80

# Zone base fare floor (§3.1)
MIN_BASE_FARE_CENTS = 100

# Pagination defaults (§2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
