"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Priority score: acuity multiplier branches
ACUITY_MULT_TIER_1 = 1.00   # working_soi == 1 and working_rom == 1
ACUITY_MULT_TIER_2 = 1.10   # working_soi == 2 and working_rom <= 2
ACUITY_MULT_TIER_3 = 1.25   # working_soi == 3 or working_rom == 3
ACUITY_MULT_TIER_4 = 1.50   # working_soi == 4 or working_rom == 4

# Priority score: length-of-stay factor branches
LOS_POST_DISCHARGE = 1.30   # current_period_index > discharge_period
LOS_ON_DISCHARGE = 1.15     # current_period_index == discharge_period
LOS_PRE_DISCHARGE = 1.00    # current_period_index < discharge_period

# Provider education band boundaries
NONE_FLOOR = 85
WATCH_FLOOR = 70
COACHING_FLOOR = 50
EDUCATION_SCORE_START = 100

# Auto-recorded education event point values
POINTS_NO_RESPONSE_ESCALATION = 3
POINTS_NO_RESPONSE_TERMINAL = 6
POINTS_CLINICALLY_UNSUPPORTED = 4
POINTS_OVERDUE = 2

# DRG weights must be at least this value
MIN_DRG_WEIGHT = 0.1000
# Program baseline CMI minimum
MIN_BASELINE_CMI = 0.1000

# Manual education-event points range
POINTS_DEDUCTED_MIN = 1
POINTS_DEDUCTED_MAX = 25

# Logical clock anchor
CLOCK_EPOCH_ISO = "2026-08-01T00:00:00Z"
