"""Domain thresholds and shared calendar — numeric constants from the PRD.

The shared season window used across the suite is
2027-01-02T00:00:00Z .. 2027-01-16T23:59:59Z (15 days, >= the 7-day minimum).
"""

# Shared season window (both instants inclusive; PRD section 2.4)
WINDOW_START = "2027-01-02T00:00:00Z"
WINDOW_END = "2027-01-16T23:59:59Z"
WINDOW_START_DATE = "2027-01-02"

# Standard site/zone fixture dates (inside the window)
SITE_OPEN_DATE = WINDOW_START
SITE_CLOSE_DATE = WINDOW_END
ZONE_COLLECTION_DATE = "2027-01-09T00:00:00Z"

# Standard chipping-run slot in the processing tail (window_end + 14 days)
RUN_START = "2027-01-17T08:00:00Z"
RUN_END = "2027-01-17T10:00:00Z"
RUN_COMPLETE_CLOCK = "2027-01-17T08:30:00Z"

# Standard mulch event windows
CLAIM_OPEN_AT = "2027-01-18T00:00:00Z"
CLAIM_CLOSE_AT = "2027-01-22T23:59:59Z"
CLAIM_WINDOW_CLOCK = "2027-01-18T12:00:00Z"
PICKUP_START = "2027-01-23T09:00:00Z"
PICKUP_END = "2027-01-23T15:00:00Z"
PICKUP_WINDOW_CLOCK = "2027-01-23T10:00:00Z"

# Per-tree weight estimates in tons (PRD section 2.8 EST_TONS table)
EST_TONS = {
    "SMALL": 0.020,
    "MEDIUM": 0.035,
    "LARGE": 0.050,
    "MIXED": 0.030,
}

# Chipping yield per material class in cubic yards per ton (PRD section 2.8)
YIELD_CY_PER_TON = {
    "MIXED_CONIFER": 2.2,
    "HARDWOOD": 1.8,
    "MIXED_LOAD": 2.0,
}

THRESHOLDS = {
    "PARTICIPANT_RESERVE_PCT": 0.60,
    "MIN_CLAIM_CY": 0.5,
    "DEFAULT_PER_HOUSEHOLD_CAP_CY": 2.0,
    "YIELD_VARIANCE_THRESHOLD": 0.08,
    "STRIKE_THRESHOLD": 2,
    "POSTURE_TICKET_THRESHOLD": 3,
    "NO_SHOW_LIMIT": 3,
    "GRADE_A_THRESHOLD": 0.9000,
    "GRADE_B_THRESHOLD": 0.7500,
    "MIN_PROGRAM_WINDOW_DAYS": 7,
    "PROCESSING_TAIL_DAYS": 14,
    "ZONE_RESCHEDULE_LEAD_HOURS": 48,
    "APPEAL_WINDOW_HOURS": 72,
    "SHIFT_CANCEL_CUTOFF_HOURS": 24,
    "RUN_BUFFER_HOURS": 2,
}

TEST_DEFAULTS = {
    "TARGET_DIVERSION_RATE": 0.9,
    "VOLUNTEER_SLOTS_PER_ROLE": 3,
    "ZONE_DAILY_TREE_CAPACITY": 5,
    "SITE_CAPACITY_CY": 100,
}
