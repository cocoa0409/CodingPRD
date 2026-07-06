"""Domain thresholds — numeric constants from the PRD.

Speed-band multipliers (PRD 3.4) and the standard program fiscal config used
across the design-index recipes.
"""

# Speed-band multipliers (PRD 3.4).
SPEED_BAND_1_MULT = 1.0   # amount over <= 10 mph
SPEED_BAND_2_MULT = 1.5   # 11..20 mph over
SPEED_BAND_3_MULT = 2.5   # 21+ mph over

# Standard program fiscal configuration used by design-index recipes.
STANDARD_PROGRAM = {
    "base_red_light_fine_cents": 10000,
    "base_speed_fine_cents": 8000,
    "admin_fee_cents": 2500,
    "late_fee_cents": 4000,
    "response_window_days": 30,
    "repeat_offender_window_days": 365,
    "repeat_offender_surcharge_pct": 0.5,
}

# Logical clock startup default (PRD 2.9).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
