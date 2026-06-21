"""Domain thresholds — numeric constants from PRD calculations (PRD §3.5, §3.6)."""

# Base SLA windows in minutes by severity (PRD §3.5).
ACK_SLA_MINUTES = {"SEV1": 15, "SEV2": 30, "SEV3": 120, "SEV4": 480}
RESOLVE_SLA_MINUTES = {"SEV1": 240, "SEV2": 480, "SEV3": 1440, "SEV4": 4320}

# Event-based fixed budget cost per severity (PRD §3.5).
EVENT_COST_MINUTES = {"SEV1": 60, "SEV2": 30, "SEV3": 10, "SEV4": 5}

# Effective ack tightening (PRD §3.5).
BUDGET_PRESSURE_FACTOR = 0.5      # EXHAUSTED service
WARNING_PRESSURE_FACTOR = 0.75    # WARNING service
SLA_FLOOR_MINUTES = 5

# Budget posture warning threshold (PRD §3.5).
WARNING_THRESHOLD_PCT = 0.8

# Business-hours variant window (PRD §3.5).
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 17

# Maintenance window spacing buffer (PRD §3.6).
MIN_WINDOW_GAP_MINUTES = 30

# Default escalation policy repeat rounds (PRD §3.1).
DEFAULT_REPEAT_ROUNDS = 1
# Default schedule handoff interval (PRD §3.1).
DEFAULT_HANDOFF_INTERVAL_HOURS = 168

TEST_DEFAULTS = {
    "ERROR_BUDGET_MINUTES": 1000,
    "TIER": "TIER_2",
}
