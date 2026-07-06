"""Domain thresholds — numeric constants from PRD calculations (PRD §2, §3.3, §3.6, §3.7, §3.8)."""

# SLA due (positive-response deadline) — PRD §3.3
EMERGENCY_WINDOW_HOURS = 2            # EMERGENCY: flat +2h
NORMAL_WINDOW_BUSINESS_DAYS = 2      # NORMAL: 2 business days, skipping weekends

# Assignment (field-completion) SLA — PRD §3.6
NORMAL_ASSIGNMENT_MINUTES = 240      # base minutes for NORMAL tickets
HIGH_PRIORITY_FACTOR = 0.5           # high-priority multiply (ceil after)
LOAD_THRESHOLD = 3                   # pre-dispatch active count >= this adds slack
LOAD_SLACK_MINUTES = 60             # slack minutes added for a loaded tech
DEFAULT_EMERGENCY_CONTACT_MINUTES = 60  # member default emergency_contact_minutes

# Dig window / mark-out validity — PRD §3.7
MARKOUT_VALID_DAYS = 21             # completed_at + 21 days

# Liability apportionment — PRD §3.8
WITHIN_MARKS_EXCAVATOR_PCT = 0.25   # dug_within_marks == true
OUTSIDE_MARKS_EXCAVATOR_PCT = 0.75  # dug_within_marks == false

# High-priority facility types — PRD §3.1
HIGH_PRIORITY_FACILITY_TYPES = ["GAS", "OIL"]

# Logical clock default before any set — PRD §2.8
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Test defaults
TEST_DEFAULTS = {
    "COVERING_POLYGON": {"min_x": 0, "min_y": 0, "max_x": 100, "max_y": 100},
    "DIG_POLYGON": {"min_x": 10, "min_y": 10, "max_x": 20, "max_y": 20},
}
