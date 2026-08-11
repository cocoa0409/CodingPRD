"""Domain constants stated in the PRD prose.

Every value here is quoted from PRD section 2 or 3; nothing is inferred.
"""

# The logical clock reads exactly this instant before any client sets it.
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# PRD 3.3: a stop "is stamped with a trip_fee_cents of 12500".
TRIP_FEE_CENTS = 12500

# PRD 3.3: "A routine stop must reserve at least 15 minutes."
MIN_STOP_SERVICE_MINUTES = 15
# PRD 3.3: "a STAT stop's service time is forced to 30 minutes".
STAT_STOP_SERVICE_MINUTES = 30
# PRD 3.3: "expanded by a 10-minute buffer on both sides".
STOP_BUFFER_MINUTES = 10

# PRD 3.1: mobile-unit ceilings and their defaults.
DEFAULT_MAX_STOPS = 3
DEFAULT_MAX_SHIFT_MINUTES = 300

# PRD 3.1 / 2.5: clinic business-calendar defaults.
DEFAULT_BUSINESS_OPEN_MINUTE = 480
DEFAULT_BUSINESS_CLOSE_MINUTE = 1020
DEFAULT_BUSINESS_DAYS = [0, 1, 2, 3, 4]

# PRD 2.8 rung 28 / 3.5: "usage_count_since_qc must be strictly less than 3".
EQUIPMENT_USAGE_CAP_BETWEEN_QC = 3
# PRD 2.8 rung 33: "read_attempt_count must be strictly less than 3".
READ_ATTEMPT_CAP = 3
# PRD 2.8 rung 34: "open_read_count must be strictly less than 2".
SPECIALIST_MAX_OPEN_READS = 2
# PRD 3.9: "A study may spawn at most two replacements".
REPEAT_CAP_PER_STUDY = 2

# PRD 3.8: turnaround budgets.
TAT_ROUTINE_TARGET_BUSINESS_MINUTES = 240
TAT_STAT_TARGET_WALL_MINUTES = 60
# PRD 2.8 rung 38 / 3.7: addendum window.
ADDENDUM_WINDOW_DAYS = 14

# PRD 3.9: "radiography 18000 cents, ultrasound 26000, CT 52000, echo 34000".
LIST_PRICE_CENTS = {
    "RADIOGRAPHY": 18000,
    "ULTRASOUND": 26000,
    "CT": 52000,
    "ECHO": 34000,
}
# PRD 3.9: "14000 cents for radiography, 20000 for ultrasound, 42000 for CT,
# 27000 for echo".
BLOCK_RATE_CENTS = {
    "RADIOGRAPHY": 14000,
    "ULTRASOUND": 20000,
    "CT": 42000,
    "ECHO": 27000,
}

# PRD 3.8: "adds the 4500-cent STAT surcharge".
STAT_SURCHARGE_CENTS = 4500
# PRD 3.9: "3 percent of the sum of base_price_cents, trip_share_cents and
# stat_surcharge_cents, rounded half up".
ADMIN_FEE_RATE_PERCENT = 3

# PRD 3.9: cancellation lead-time tiers, in wall minutes.
CANCEL_FREE_LEAD_MINUTES = 1440
CANCEL_HALF_LEAD_MINUTES = 240
