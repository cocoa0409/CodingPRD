"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# PRD §2.5: the logical clock reads exactly this instant before any
# clock-setting call.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD §3.3: grade multipliers for the core credit calculation.
GRADE_MULTIPLIERS = {
    "GRADE_A": 1.00,
    "GRADE_B": 0.60,
    "GRADE_C": 0.30,
    "REJECT": 0.00,
}

# PRD §3.3: provisional variant multiplier (assumes a perfect GRADE_A core).
PROVISIONAL_MULT = 1.00

# PRD §3.3: per-part deduction amounts (cents).
COMPONENT_DEDUCTION_CENTS = {
    "CRANKSHAFT": 40000,
    "CYLINDER_HEAD": 25005,
    "ENGINE_BLOCK": 50000,
    "CAMSHAFT": 33335,
}

# PRD §3.4: aging brackets with inclusive upper bounds; above 90 days the
# deposit is forfeited (0%).
BRACKET_1_MAX_DAYS = 30
BRACKET_1_PCT = 1.00
BRACKET_2_MAX_DAYS = 60
BRACKET_2_PCT = 0.80
BRACKET_3_MAX_DAYS = 90
BRACKET_3_PCT = 0.50
FORFEIT_AFTER_DAYS = 90

# PRD §3.11: warranty term and proration granularity.
WARRANTY_MONTHS = 12
DAYS_PER_MONTH = 30
WARRANTY_WINDOW_DAYS = 360  # 12 x 30-day months; filing must be < 360 days

# PRD §3.8: dyno cell cooldown buffer.
DYNO_CELL_COOLDOWN_MINUTES = 30

# Standard build-spec commercials used across tests.
DEFAULT_LIST_PRICE_CENTS = 250000
DEFAULT_CORE_DEPOSIT_CENTS = 200000
DEFAULT_CORE_BASE_CREDIT_CENTS = 100000
DEFAULT_DYNO_MIN_HORSEPOWER = 300
DEFAULT_DYNO_MIN_OIL_PRESSURE_PSI = 20.0
DEFAULT_DYNO_MAX_COOLANT_TEMP_F = 210

# Passing dyno measurements for the default thresholds (320 >= 300,
# 25.0 >= 20.0, 195 <= 210).
PASSING_DYNO = {
    "horsepower": 320,
    "oil_pressure_psi": 25.0,
    "coolant_temp_f": 195,
}
