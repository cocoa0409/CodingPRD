"""Domain thresholds — numeric constants stated in the PRD workflows."""

# Posture ladder (noise branch) and noise window
NOISE_BREACH_CAUTION_THRESHOLD = 1
NOISE_BREACH_SUSPENSION_THRESHOLD = 3
NOISE_WINDOW_MINUTES = 60

# Cancellation / refund pricing (integer cents)
FEE_PER_DRIVER_CENTS = 35000
FULL_REFUND_HOURS = 72
HALF_REFUND_HOURS = 24
WEATHER_FACILITY_FEE_CENTS = 5000

# Garage utility pricing (integer cents)
GARAGE_BASE_FEE_CENTS = 15000
POWER_TIER1_CENTS = 2500
POWER_TIER2_CENTS = 4000
WATER_FLAT_CENTS = 3000

# Coach load cap
MAX_BOOKINGS_PER_COACH = 3

# Logical clock: server boot instant per the PRD, plus convenient later instants
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
FAR_FUTURE_ISO = "2030-01-01T00:00:00Z"
