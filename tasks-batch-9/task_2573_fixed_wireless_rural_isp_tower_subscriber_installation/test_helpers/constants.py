"""Numeric thresholds and defaults quoted from PRD 2 and PRD 3."""

# The logical clock's startup reading (PRD 2.4).
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# Line-of-sight / mast geometry (PRD 3.5, PRD 3.7).
LOS = {
    "SAFETY_MARGIN_M": 0.5,
    "MAST_STEP_M": 0.5,
    "MAX_MAST_HEIGHT_M": 12.0,
    "MAX_LINK_DISTANCE_KM": 15.0,
    "PARTIAL_OBSTRUCTION_EXTRA_M": 1.0,
    "CLEARANCE_M_AT_OR_BELOW_3KM": 1.5,
    "CLEARANCE_M_3_TO_8KM": 3.0,
    "CLEARANCE_M_8_TO_15KM": 4.5,
    "QUALIFICATION_VALID_DAYS": 30,
}

# Mounting band ceilings, in metres (PRD 3.5, PRD 3.7).
MOUNTING_CEILING_M = {
    "WALL_BRACKET": 1.0,
    "NON_PEN_ROOF_TRIPOD": 3.0,
    "ROOF_MAST_GUYED": 6.0,
    "GROUND_POLE_MAST": 12.0,
}

# Sector posture bands, expressed as fractions of the sector's own ceiling (PRD 3.3).
POSTURE = {
    "WATCH_FRACTION": 0.5,
    "HOLD_FRACTION": 0.75,
    "FREEZE_FRACTION": 1.0,
    "BACKHAUL_ESCALATION_RATIO": 12.0,
    "DEFAULT_MAX_OVERSUBSCRIPTION_RATIO": 8.0,
}

# Capacity reservation windows (PRD 3.6).
HOLD = {
    "DEFAULT_HOLD_DAYS": 14,
    "MIN_HOLD_DAYS": 1,
    "MAX_HOLD_DAYS": 30,
    "AUTO_PROMOTION_HOLD_DAYS": 14,
}

# Metered cycles and deprioritization (PRD 3.8).
CYCLE = {
    "CYCLE_DAYS": 30,
    "STICKY_BREACH_CYCLES": 2,
    "MIN_EFFECTIVE_MBPS": 0.1,
}

# Install invoice pricing (PRD 3.7).
INVOICE = {
    "TRIP_CHARGE_CENTS": 9900,
    "LABOR_WALL_BRACKET_CENTS": 4900,
    "LABOR_NON_PEN_ROOF_TRIPOD_CENTS": 9900,
    "LABOR_ROOF_MAST_GUYED_CENTS": 19900,
    "LABOR_GROUND_POLE_MAST_CENTS": 34900,
    "MAST_KIT_CENTS_PER_HALF_METRE": 1750,
    "DISCOUNT_TIER_3_MIN_SUBTOTAL_CENTS": 30000,
    "DISCOUNT_TIER_3_CENTS": 5000,
    "DISCOUNT_TIER_2_MIN_SUBTOTAL_CENTS": 20000,
    "DISCOUNT_TIER_2_CENTS": 3000,
    "DISCOUNT_TIER_1_MIN_SUBTOTAL_CENTS": 10000,
    "DISCOUNT_TIER_1_CENTS": 1000,
    "REG_RECOVERY_PCT": 0.0325,
}

# Customer premises equipment settlement (PRD 3.6, PRD 3.8).
EQUIPMENT = {
    "REPLACEMENT_COST_CENTS": 34900,
    "RENTAL_MONTHLY_CENTS": 1000,
    "PURCHASE_PRICE_CENTS": 29900,
    "RENTAL_CREDIT_CAP_PCT": 0.6,
    "DAMAGE_CHARGE_PCT": 0.5,
    "DEPRECIATION_MONTHS": 36,
    "RESTOCK_FEE_PCT": 0.15,
    "RETURN_WINDOW_DAYS": 21,
    "DAYS_PER_SETTLEMENT_MONTH": 30,
}

# Service-level credits and outage exclusions (PRD 3.9).
SLA = {
    "MONTHLY_MINUTES": 43200,
    "SHORTFALL_MULTIPLIER": 10,
    "MAX_CREDIT_PCT_OF_MONTHLY_PRICE": 0.5,
    "MIN_CREDITABLE_MINUTES": 60,
    "SEVERE_WIND_MPH": 58.0,
    "PLANNED_NOTICE_MIN_DAYS": 7,
}

# Loop bounds (PRD 3.4, PRD 3.7).
LIMITS = {
    "COORDINATION_ROUND_LIMIT": 3,
    "RESURVEY_LIMIT": 2,
}

# Ground lease escalation (PRD 3.1).
LEASE = {
    "MONTHS_PER_LEASE_YEAR": 12,
    "MIN_TERM_MONTHS": 12,
    "MAX_TERM_MONTHS": 240,
}

# Pagination bounds (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
