"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

# Banking cap on the allowable-increase fraction (§3.3).
BANKED_CAP_PCT = 0.16

# Hardship-petition passthrough cap fraction (§3.5).
HARDSHIP_CAP_PCT = 0.08

# Capital-improvement bedroom-tiered monthly cap fractions (§3.5).
CAPITAL_CAP_PCT_LE_1BR = 0.05     # <= 1 bedroom
CAPITAL_CAP_PCT_2_TO_3BR = 0.06   # 2 or 3 bedrooms
CAPITAL_CAP_PCT_GE_4BR = 0.07     # >= 4 bedrooms

# Overcharge-penalty constants (§3.9).
TREBLE_MULTIPLIER = 3
MONTHLY_INTEREST_RATE = 0.0075
LATE_REG_PENALTY_CENTS = 50000
FAIL_FILE_PENALTY_CENTS = 100000

# Service-decrease fractions (§3.6).
SUBSTANTIAL_DECREASE_PCT = 0.25
MINOR_DECREASE_PCT = 0.10

# Buyout cooling-off and floor (§3.7).
COOLING_OFF_DAYS = 30
RELOCATION_MIN_CENTS = 500000

# Hearing officer scheduling buffer (§3.5).
HEARING_BUFFER_MINUTES = 30

# Vacancy decontrol rent threshold (§3.8).
DECONTROL_RENT_THRESHOLD_CENTS = 500000

# The logical clock's startup default (§2.7).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


TEST_DEFAULTS = {
    "BASE_RENT_CENTS": 300000,
    "BEDROOMS": 2,
}
