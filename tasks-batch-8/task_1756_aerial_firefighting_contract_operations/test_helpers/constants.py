"""Domain thresholds and test defaults — numeric constants from PRD rules."""

# The logical clock starts here before any explicit set (PRD logical-clock rule).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Default available-minutes threshold for a full-rate exclusive-use day.
    "DEFAULT_MIN_DAILY_MINUTES": 570,
    # Daily flight-hour limit in tenths of an hour (8.0 h).
    "DAILY_FLIGHT_LIMIT_TENTHS": 80,
    # Duty-day span limit in minutes (14 h).
    "CREW_DAY_LIMIT_MINUTES": 840,
    # Minimum rest gap around a pilot's assignment windows.
    "REST_BUFFER_MINUTES": 60,
    # Reload turn SLA: breach only when the average is strictly greater.
    "RELOAD_SLA_MINUTES": 30.0,
    # Invoice compliance ratio below which the 5% penalty applies.
    "COMPLIANCE_THRESHOLD": 0.98,
    "PENALTY_RATE": 0.05,
    # Reconciliation match tolerance in tenths of an hour.
    "MATCH_TOLERANCE_TENTHS": 1,
}

TEST_DEFAULTS = {
    "CONTRACT_NUMBER": "EU-2026-001",
    "AGENCY": "USFS",
    "CONTRACT_TYPE": "EXCLUSIVE_USE",
    "DAILY_AVAILABILITY_RATE_CENTS": 500000,
    "FLIGHT_HOUR_RATE_CENTS": 300000,
    "SEASON_START_DATE": "2026-06-01",
    "SEASON_END_DATE": "2026-09-30",
    "SEASON_FLIGHT_HOUR_CAP_TENTHS": 20000,
    "ACCEPTANCE_WINDOW_MINUTES": 30,
    "TAIL_NUMBER": "N100AF",
    "AIRCRAFT_MODEL": "AT-802F",
    "TANK_CAPACITY_GALLONS": 800,
    "PILOT_NAME": "Pat Reed",
    "INCIDENT_NUMBER": "USFS-2026-0801",
    "INCIDENT_NAME": "Ridge Fire",
    "INCIDENT_LOCATION": "39.5,-121.5",
    "ORDER_NUMBER": "O-1001",
    "INSPECTION_SCHEDULED_FOR": "2026-07-15T08:00:00Z",
    "INSPECTION_COMPLETED_AT": "2026-07-15T09:00:00Z",
    "VALID_DAYS": 365,
    "SUBMIT_CLOCK": "2026-08-09T00:00:00Z",
}
