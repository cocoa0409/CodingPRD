"""Domain thresholds — numeric constants from the PRD fee, deposit, penalty, and scoring rules."""

# Permit fee (§3.4), integer cents
BASE_APPLICATION_FEE_CENTS = 25000
PER_DAY_RATE_CENTS = 15000
ROAD_CLOSURE_PER_BOOKING_CENTS = 40000
PARKING_PER_DAY_CENTS = 10000
DRONE_RIDER_FEE_CENTS = 30000
STILL_PHOTO_RIDER_FEE_CENTS = 5000

# Crew surcharge tiers (§3.4)
CREW_TIER_16_50_CENTS = 20000
CREW_TIER_51_150_CENTS = 50000
CREW_TIER_OVER_150_CENTS = 100000

# Municipal surcharge (§3.4), basis points keyed on the pre-surcharge subtotal tier
SURCHARGE_TIER1_BPS = 300     # subtotal < 100000
SURCHARGE_TIER2_BPS = 500     # 100000 <= subtotal < 300000
SURCHARGE_TIER3_BPS = 700     # subtotal >= 300000
SURCHARGE_TIER1_CEIL_CENTS = 100000
SURCHARGE_TIER2_CEIL_CENTS = 300000

# Deposit (§3.5)
DEPOSIT_BASE_PCT_BPS = 2000
DEPOSIT_HIGH_PCT_BPS = 2500
DEPOSIT_HIGH_VALUE_CENTS = 500000
ROAD_CLOSURE_BOND_PER_BOOKING_CENTS = 50000

# Late-wrap penalty (§3.8)
LATE_HOURLY_PENALTY_CENTS = 20000

# Compliance score weights (§3.8)
COMPLIANCE_BASE = 100
LATE_WRAP_POINTS = 10
DAMAGE_POINTS = 15
MISSED_NOTICE_POINTS = 20

# Neighborhood notification lead time (§3.7)
NOTIFICATION_MIN_LEAD_DAYS = 7

# Road-closure setup buffer (§3.5), minutes each side
SETUP_BUFFER_MINUTES = 60
