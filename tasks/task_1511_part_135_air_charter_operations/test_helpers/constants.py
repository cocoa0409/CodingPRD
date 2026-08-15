"""Domain thresholds and rate constants from the PRD's calculation rules."""

# Logical clock default (PRD: "the logical clock reads exactly 2026-08-01T00:00:00Z").
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Quote pricing (category rate card, cents per block hour).
CATEGORY_RATE_CENTS_PER_HOUR = {
    "TURBOPROP": 150000,
    "LIGHT_JET": 250000,
    "MIDSIZE_JET": 400000,
    "HEAVY_JET": 650000,
}
POSITIONING_RATE_FACTOR = 0.6
DISCOUNT_TIER1_THRESHOLD_CENTS = 2000000
DISCOUNT_TIER1_PCT = 0.05
DISCOUNT_TIER2_THRESHOLD_CENTS = 5000000
DISCOUNT_TIER2_PCT = 0.10
FUEL_SURCHARGE_PCT = 0.08
FUEL_STOP_FEE_CENTS = 15000
INTL_FEE_CENTS = 250000
DEPOSIT_PCT = 0.25
QUOTE_VALIDITY_HOURS = 48

# Final pricing.
MIN_BILLED_REVENUE_LEG_MINUTES = 60

# Crew legality.
DUTY_MAX_MINUTES = 840
REST_MIN_MINUTES = 600
REPORT_DEBRIEF_MINUTES = 60
REPORT_MINUTES = 30
DEBRIEF_MINUTES = 30

# Airframe inspection horizon (100 hours).
CHECK_INTERVAL_MINUTES = 6000

# Occupancy turnaround buffer.
TURNAROUND_BUFFER_MINUTES = 45

# Time-based expiry.
TSA_VALIDITY_HOURS = 72
PERMIT_VALIDITY_DAYS = 30

# Cancellation refund tiers (hours before departure).
TIER_FULL_REFUND_HOURS = 72
TIER_HALF_REFUND_HOURS = 24
FEE_PCT_TIER1 = 0.10
FEE_PCT_TIER2 = 0.50
FEE_PCT_TIER3 = 1.00

# Precomputed quote totals for the canonical fixture itineraries:
# LIGHT_JET leg REV 60 -> quote 270000, deposit 67500, balance 202500
# LIGHT_JET legs REV 120 + POS 30 -> quote 621000, deposit 155250, balance 465750
# LIGHT_JET leg REV 480 -> quote 2052000, deposit 513000, balance 1539000
# LIGHT_JET leg REV 61 -> quote 274500, deposit 68625, balance 205875
# MIDSIZE_JET REV 120 fuel_stop + intl -> quote 1129000, deposit 282250
# HEAVY_JET leg REV 60 -> quote 702000, deposit 175500, balance 526500
QUOTE_LJ_60 = 270000
DEPOSIT_LJ_60 = 67500
BALANCE_LJ_60 = 202500
