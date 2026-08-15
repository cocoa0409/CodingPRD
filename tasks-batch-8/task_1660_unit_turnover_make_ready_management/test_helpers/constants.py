"""Domain thresholds and constants — numeric rules from the PRD."""

# PRD §2.5: startup value of the logical clock.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# PRD §3.4: property-management overhead allocation on booked expense.
OVERHEAD_BP = 250

# PRD §3.6: repair-affordability ceiling ratio under PERCENT_OF_REPLACE.
REPAIR_REPLACE_RATIO = 0.5

# PRD §3.3/§3.4: mandatory cure day before carpet after paint.
CURE_BUFFER_DAYS = 1

# PRD §3.3: per-category standard durations used by the projection.
STANDARD_DAYS = {
    "REPAIR": 2,
    "PAINT": 2,
    "CARPET": 1,
    "CLEAN": 1,
    "APPLIANCE": 1,
    "FIXTURE": 1,
    "OTHER": 1,
}

# PRD §3.2: category scheduling order.
SEQUENCE_RANK = {
    "REPAIR": 1,
    "APPLIANCE": 2,
    "FIXTURE": 3,
    "PAINT": 4,
    "CARPET": 5,
    "CLEAN": 6,
    "OTHER": 7,
}

# Shared property policy used by most scenarios: 5-day target, 10% PM
# auto-approve band, 30% RM band, 50000-cent capital threshold.
DEFAULT_PROPERTY = {
    "name": "Sunset Arms",
    "days_to_ready_target": 5,
    "pm_threshold_bp": 1000,
    "rm_threshold_bp": 3000,
    "capital_threshold_cents": 50000,
    "replacement_policy": "PERCENT_OF_REPLACE",
}

TEST_DEFAULTS = {
    "UNIT_NUMBER": "101",
    "SQUARE_FEET": 800,
    "NOTICE_DATE": "2026-07-28",
    "MOVE_OUT_DATE": "2026-07-31",
    "ITEM_ESTIMATE": 5000,
    "APPLICANT_NAME": "A Lee",
}
