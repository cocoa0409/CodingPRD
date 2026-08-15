"""Domain thresholds and logical-clock constants from the PRD."""

# Logical clock (PRD section 3.12): the server starts here and only advances
# when the PlatformAdmin drives it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Open-ocean exchange minimum distance (nautical miles).
    "OPEN_OCEAN_MIN_NM": 200,
    # Sampling statutory limits (PRD section 3.5).
    "ORGANISM_LIMIT": 10.0,
    "TSS_LIMIT": 50.0,
    # Company-internal stricter limits (PRD section 3.5).
    "INTERNAL_ORGANISM_LIMIT": 5.0,
    "INTERNAL_TSS_LIMIT": 25.0,
    # Physically implausible inshore exchange floor (PRD section 3.2).
    "EXCHANGE_MIN_PLAUSIBLE_NM": 3.0,
    # Sulfur limits (PRD section 3.8).
    "ECA_SULFUR_LIMIT_PCT": 0.10,
    "GLOBAL_SULFUR_LIMIT_PCT": 0.50,
    "SULFUR_INPUT_MAX_PCT": 5.0,
    # Reporting deadlines (PRD section 3.4).
    "PRE_ARRIVAL_LEAD_HOURS": 24,
    "POST_DISCHARGE_GRACE_HOURS": 6,
    # Severity score bands (PRD section 3.10).
    "CRITICAL_THRESHOLD": 70,
    "MAJOR_THRESHOLD": 40,
    # Severity response deadlines.
    "MINOR_RESPONSE_DAYS": 30,
    "MAJOR_RESPONSE_DAYS": 14,
    "CRITICAL_RESPONSE_HOURS": 72,
    # Escalation timing (PRD section 3.10).
    "ESCALATION_GRACE_DAYS": 7,
    "CRITICAL_ESCALATION_HOURS": 24,
    # Inspection appeal window (PRD section 3.5).
    "REOPEN_WINDOW_DAYS": 90,
    # Drill overdue grace (PRD section 3.9).
    "DRILL_OVERDUE_DAYS": 30,
}

TEST_DEFAULTS = {
    "BALLAST_CAPACITY_M3": 30000,
    "EXCHANGE_DISTANCE_NM": 200,
    "DEPARTED_AT": "2026-07-28T00:00:00Z",
    "ARRIVED_AT": "2026-08-10T00:00:00Z",
}

# Recurrence intervals per drill kind in days (PRD section 3.9).
DRILL_RECURRENCE_DAYS = {
    "BWMS_OPERATION": 90,
    "EMERGENCY_BALLAST_EXCHANGE": 180,
    "OIL_SPILL_RESPONSE": 90,
    "SEWAGE_SYSTEM": 180,
    "GARBAGE_MANAGEMENT": 180,
    "MARPOL_AWARENESS": 365,
}
