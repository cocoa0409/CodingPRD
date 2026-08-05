"""Domain thresholds and canonical rate-card values from the PRD calculations (§3)."""

# Governing fee-schedule values used by the canonical rate card (§3.1).
FEE_SCHEDULE = {
    "WATER_CAPACITY_FEE_PER_ERU_CENTS": 400000,
    "SEWER_CAPACITY_FEE_PER_ERU_CENTS": 500000,
    "USE_MULT_RESIDENTIAL": 1.00,
    "USE_MULT_COMMERCIAL": 1.15,
    "USE_MULT_IRRIGATION": 1.30,
    "ADMIN_FEE_PCT": 0.03,
    "ADMIN_FEE_CAP_CENTS": 50000,
    "VOLUME_DISCOUNT_THRESHOLD_CENTS": 2000000,
    "VOLUME_DISCOUNT_PCT": 0.05,
    "PAVEMENT_CUT_SURCHARGE_CENTS": 80000,
}

# Threshold constants (§3.3, §3.5).
THRESHOLDS = {
    "MAX_CONNECTION_DISTANCE_FT": 200,
    "APPOINTMENT_BUFFER_MINUTES": 60,
}

# Canonical meter-size schedule row used across fixtures (§3.1).
METER_ONE = {
    "meter_size": "ONE",
    "eru_factor": 2.5,
    "tap_install_fee_cents": 250000,
}

METER_FIVE_EIGHTH = {
    "meter_size": "FIVE_EIGHTH",
    "eru_factor": 1.0,
    "tap_install_fee_cents": 150000,
}
