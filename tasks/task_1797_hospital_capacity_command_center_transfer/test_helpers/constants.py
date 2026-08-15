"""Domain thresholds — numeric constants stated in the PRD."""

THRESHOLDS = {
    # Load scoring / diversion recommendation
    "HELD_WEIGHT": 0.5,
    "BOARDING_WEIGHT": 0.75,
    "INBOUND_WEIGHT": 0.5,
    "DIVERSION_RECOMMEND_THRESHOLD": 95.0,
    # Forecast census projection
    "ED_CONVERSION_RATE": 0.8,
    "ELECTIVE_BUFFER": 2,
    # Selector scoring
    "SERVICE_MATCH_POINTS": 1000,
    "ACUITY_FIT_BASE": 4,
    "ACUITY_FIT_POINTS": 100,
    "ISO_EXACT_POINTS": 10,
    "UNIT_PREFERENCE_POINTS": 5,
    # Boarding escalation
    "BOARDING_HUDDLE_THRESHOLD_MINUTES": 120,
    "EXECUTIVE_ESCALATION_MINUTES": 240,
    "HUDDLE_MAX_PER_WINDOW": 3,
    "HUDDLE_WINDOW_HOURS": 24,
    # Hold lifecycle
    "HOLD_TTL_MINUTES": 60,
    "EXTEND_MINUTES": 30,
    "HOLD_EXTEND_MAX": 2,
    "HOLD_QUOTA_PER_FACILITY": 6,
    # Consult
    "CONSULT_TTL_MINUTES": 30,
    # Diversion lift minimum duration
    "MIN_DIVERSION_MINUTES": 30,
    # Rebalance margin
    "REBALANCE_MARGIN": 10.0,
}

# The server starts with the logical clock reading exactly this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "FACILITY_NAME": "Command Center Facility",
    "REGION": "R1",
    "SOURCE_FACILITY_NAME": "St Elsewhere",
    "TURNOVER_MINUTES": 45,
}

# Fixed ISO instants used across tests (all on the logical-clock timeline).
T_0000 = "2026-08-01T00:00:00Z"
T_0020 = "2026-08-01T00:20:00Z"
T_0030 = "2026-08-01T00:30:00Z"
T_0045 = "2026-08-01T00:45:00Z"
T_0059 = "2026-08-01T00:59:00Z"
T_0100 = "2026-08-01T01:00:00Z"
T_0114 = "2026-08-01T01:14:00Z"
T_0115 = "2026-08-01T01:15:00Z"
T_0130 = "2026-08-01T01:30:00Z"
T_0200 = "2026-08-01T02:00:00Z"
T_0300 = "2026-08-01T03:00:00Z"
T_0400 = "2026-08-01T04:00:00Z"
T_0500 = "2026-08-01T05:00:00Z"
