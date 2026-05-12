"""Domain constants from PRD prose.

These values are quoted from the PRD prose; tests use them to drive
boundary-precision and side-effect assertions deterministically.
"""
from __future__ import annotations

# Fleet defaults (PRD section 2.4, section 3.6, section 3.8, section 3.10)
FLEET_INITIAL_CLOCK = "1970-01-01T00:00:00.000Z"
DEFAULT_CHARGING_LOW_THRESHOLD_PCT = 20
DEFAULT_CHARGING_OPPORTUNITY_PCT = 60
DEFAULT_CHARGING_FULL_PCT = 95
DEFAULT_SLOT_SECONDS = 10
DEFAULT_TASK_EXPIRY_SECONDS = 600
DEFAULT_DEADLOCK_WAIT_SECONDS = 30

# Heartbeat (PRD section 3.4: "the heartbeat-timeout constant of fifteen seconds")
HEARTBEAT_TIMEOUT_SECONDS = 15

# Rollback ceiling (PRD section 3.9: "the rollback ceiling of three")
MAX_ROLLBACKS = 3

# Priority bases for priority_score (PRD section 3.5)
PRIORITY_BASE = {
    "CRITICAL": 0,
    "HIGH": 1000,
    "NORMAL": 2000,
    "LOW": 3000,
}
AGING_BUCKET_SECONDS = 60  # PRD section 3.5: "sixty-second buckets"
AGING_BUCKET_WEIGHT = 10  # PRD section 3.5: "multiplied by ten"

# Deadlock penalty (PRD section 3.6: "deadlock penalty constant - a value of one thousand")
DEADLOCK_PENALTY = 1000

# Metrics defaults (PRD section 3.11)
DEFAULT_WINDOW_SECONDS = 3600
BOTTLENECK_TOP_K = 5

# Pagination (PRD section 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Charge progression precision: integer second granularity (PRD section 2.9)
# Battery is integer percent.
BATTERY_MAX = 100

# Manhattan-1 isolation: nodes within Manhattan distance 1 of the robot's position
ISOLATION_MANHATTAN_DISTANCE = 1


__all__ = [
    "FLEET_INITIAL_CLOCK",
    "DEFAULT_CHARGING_LOW_THRESHOLD_PCT",
    "DEFAULT_CHARGING_OPPORTUNITY_PCT",
    "DEFAULT_CHARGING_FULL_PCT",
    "DEFAULT_SLOT_SECONDS",
    "DEFAULT_TASK_EXPIRY_SECONDS",
    "DEFAULT_DEADLOCK_WAIT_SECONDS",
    "HEARTBEAT_TIMEOUT_SECONDS",
    "MAX_ROLLBACKS",
    "PRIORITY_BASE",
    "AGING_BUCKET_SECONDS",
    "AGING_BUCKET_WEIGHT",
    "DEADLOCK_PENALTY",
    "DEFAULT_WINDOW_SECONDS",
    "BOTTLENECK_TOP_K",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "BATTERY_MAX",
    "ISOLATION_MANHATTAN_DISTANCE",
]
