"""Domain thresholds — numeric constants from the PRD pricing and lead-time rules."""

# Provisional estimate: blended per-linear-foot rate by scope (cents).
SCOPE_BALLPARK_RATE_CENTS = {"PAINT": 12000, "REFACE": 28000, "REDOOR": 45000}

# Firm quote labor rates (cents).
SCOPE_FOOT_RATE_CENTS = {"PAINT": 9000, "REFACE": 20000, "REDOOR": 30000}
SCOPE_DOOR_RATE_CENTS = {"PAINT": 1500, "REFACE": 4000, "REDOOR": 7000}

# Finish multiplier applied to the pre-finish subtotal.
FINISH_MULTIPLIER = {
    "PAINT": 1.00,
    "LAMINATE": 1.10,
    "THERMOFOIL": 1.15,
    "WOOD_VENEER": 1.25,
    "SOLID_WOOD": 1.40,
}

# Volume discount tiers (by subtotal in cents).
VOLUME_DISCOUNT_TIER_1_MIN = 1_500_000   # >= here -> 5%
VOLUME_DISCOUNT_TIER_2_MIN = 3_000_000   # >= here -> 10%

# Quote validity window (days).
QUOTE_VALID_DAYS = 30

# Change-order lead-time constants.
CO_LEAD_PER_FOOT_DAYS = 2
CO_LEAD_DOOR_FLAT_DAYS = 3
RUSH_FACTOR = 0.5

# Base lead-time constants.
FINISH_LEAD_DAYS = {
    "PAINT": 7,
    "LAMINATE": 14,
    "THERMOFOIL": 21,
    "WOOD_VENEER": 28,
    "SOLID_WOOD": 42,
}
SCOPE_LEAD_ADD_DAYS = {"PAINT": 0, "REFACE": 5, "REDOOR": 10}
VOLUME_LEAD_STEP_DAYS = 7
LARGE_JOB_FEET = 30

# Warranty window (days).
WARRANTY_DAYS = 90

# Financing.
APR_BY_TERM = {12: 0.0399, 24: 0.0599, 36: 0.0799, 48: 0.0999, 60: 0.1199}
DTI_MAX = 0.20

# Logical clock startup default.
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"
