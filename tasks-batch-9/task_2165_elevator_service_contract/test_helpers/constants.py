"""Domain thresholds and constants stated by the PRD."""

# PRD §2.5 — the logical clock reads exactly this instant on startup.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_UTC_RENDERED = "2026-08-01T00:00:00.000Z"

# PRD §3.2 — required maintenance task codes by contract scope.
FULL_MAINTENANCE_REQUIRED_TASK_CODES = [
    "BRAKE",
    "CONTROLLER",
    "DOOR_OPERATOR",
    "FIRE_SERVICE_TEST",
    "GOVERNOR",
    "PIT_CLEAN",
    "ROPES",
]
OIL_AND_GREASE_REQUIRED_TASK_CODES = [
    "LUBRICATION",
    "PIT_CLEAN",
    "VISUAL_INSPECTION",
]

THRESHOLDS = {
    # PRD §3.1 — contract escalates when two or more cars are out of service.
    "OUT_OF_SERVICE_ESCALATION_COUNT": 2,
    # PRD §3.2 — a visit already reworked twice may not be disputed again.
    "MAX_REWORK_COUNT": 2,
    # PRD §3.4 — a certificate is valid through issue date + 365 days.
    "CERTIFICATE_VALIDITY_DAYS": 365,
    # PRD §3.5 — different-typed windows on one car need 120 minutes of clear air.
    "INTER_TYPE_BUFFER_MINUTES": 120,
    # PRD §3.5 — at most one car under modernization at a time on a contract.
    "MAX_CONCURRENT_MODERNIZATION_CARS": 1,
    # PRD §3.6 — supersession walk terminates within three hops.
    "SUPERSESSION_MAX_DEPTH": 3,
    "OBSOLETE_SUBSTITUTION_PENALTY_DAYS": 10,
    "EXPEDITE_DAYS_SAVED": 7,
    "MIN_LEAD_DAYS": 3,
    "EXPEDITE_PCT_TIER_SMALL": 0.20,
    "EXPEDITE_PCT_TIER_MEDIUM": 0.15,
    "EXPEDITE_PCT_TIER_LARGE": 0.10,
    "TIER_SMALL_MAX_EXCLUSIVE_CENTS": 100_000,
    "TIER_LARGE_MIN_CENTS": 500_000,
    # PRD §3.8 — penalty inputs.
    "UPTIME_TARGET_PCT": 98.50,
    "SEVERE_SHORTFALL_PP": 2.00,
    "LATE_CALLBACK_FEE_CENTS": 25_000,
    "ENTRAPMENT_FEE_CENTS": 100_000,
    "MISSED_VISIT_FEE_CENTS": 75_000,
    "UPTIME_PENALTY_PER_PP_CENTS": 40_000,
    "PENALTY_CAP_PCT_A": 0.25,
    "SCHEDULE_B_BREACH_PCT": 0.02,
    "PENALTY_CAP_PCT_B": 0.30,
    # PRD §3.9 — performance score.
    "W_UPTIME": 0.50,
    "W_RESPONSE": 0.25,
    "W_VISIT": 0.25,
    "DRAG_DIVISOR_CENTS": 100_000,
    "PENALTY_DRAG_CAP_PTS": 15.00,
    "RENEGOTIATION_TRIGGER_SCORE": 75.00,
    "MAX_RENEGOTIATION_ROUNDS": 4,
    # PRD §3.7 — minutes in a day.
    "MINUTES_PER_DAY": 1440,
}

TEST_DEFAULTS = {
    "MONTHLY_BASE_FEE_CENTS": 400_000,
    "CALLBACK_RESPONSE_MINUTES": 60,
    "ENTRAPMENT_RESPONSE_MINUTES": 30,
    "JURISDICTION_CODE": "NY-NYC",
    "FIRE_DISTRICT_CODE": "FD-07",
    "TERM_START_DATE": "2026-01-01",
    "TERM_END_DATE": "2027-12-31",
    "CAPACITY_LBS": 3000,
}

# A syntactically valid UUID that is never minted by the server.
UNUSED_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

# PRD §3.7 — 2026-08 has 31 days, so 31 * 1440 minutes.
AUGUST_2026_PERIOD_MINUTES = 44_640
