"""Domain thresholds — numeric constants from PRD prose.

Every literal corresponds to a numeric threshold, default, or magic constant
named in PRD §2 / §3. The reference implementation is expected to use these
same literal values.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Sensors — PRD §3.1
# ---------------------------------------------------------------------------
# "polling cadence has a default of 300 seconds and must be at least 30
#  seconds and at most 3600 seconds"
SENSOR_POLL_INTERVAL_DEFAULT = 300
SENSOR_POLL_INTERVAL_MIN = 30
SENSOR_POLL_INTERVAL_MAX = 3600

# Three consecutive OUT_OF_RANGE readings classify the third as
# ABNORMAL_FILTERED — PRD §3.1
ABNORMAL_FLOW_CONSECUTIVE_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Crop water demand model — PRD §3.2
# ---------------------------------------------------------------------------
STAGE_BASE_LITERS_PER_HECTARE = {
    "SEEDLING": 20000,
    "VEGETATIVE": 35000,
    "FLOWERING": 50000,
    "FRUITING": 45000,
    "MATURE": 25000,
}
TARGET_MOISTURE_PCT = {
    "WHEAT": 60,
    "CORN": 65,
    "RICE": 80,
    "COTTON": 55,
    "VEGETABLE": 70,
}
RAINFALL_OFFSET_MM = 30
DEFAULT_MOISTURE_PCT_FALLBACK = 50  # PRD §3.2 ("if no such reading exists, the model uses 50")
DEFAULT_RAINFALL_MM_FALLBACK = 0    # PRD §3.2 ("defaulting to zero millimetres if none")

# ---------------------------------------------------------------------------
# Quotas — PRD §3.5
# ---------------------------------------------------------------------------
# "an optional warning_threshold_pct whose default is 80 and which must be
#  at least 1 and at most 100"
QUOTA_WARNING_THRESHOLD_DEFAULT = 80
QUOTA_WARNING_THRESHOLD_MIN = 1
QUOTA_WARNING_THRESHOLD_MAX = 100

# "the smaller of the prior period's unused liters and twenty percent of
#  the prior period's allocated_liters"
QUOTA_CARRY_FORWARD_CAP_PCT = 0.20

# "an extra_liters value strictly greater than zero and at most fifty
#  percent of allocated_liters"
QUOTA_OVERRIDE_EXTRA_MAX_PCT = 0.50

# Float comparison epsilon — PRD §2.6
PERCENTAGE_EPSILON = 1e-6

# ---------------------------------------------------------------------------
# Valve groups — PRD §3.3
# ---------------------------------------------------------------------------
VALVE_GROUP_VALVE_IDS_MAX_LENGTH = 16

# ---------------------------------------------------------------------------
# Tiered fee — PRD §3.6
# ---------------------------------------------------------------------------
# "the set of peak hours {6, 7, 8, 9, 18, 19, 20, 21}"
PEAK_HOURS = {6, 7, 8, 9, 18, 19, 20, 21}

# "from zero up to (but not including) one hundred thousand at thirty cents
#  per liter, liters from one hundred thousand up to (but not including)
#  two hundred fifty thousand at fifty cents per liter, and any liters
#  beyond two hundred fifty thousand at eighty cents per liter"
PEAK_TIERS = (
    (100_000, 30),
    (250_000, 50),
    (None, 80),  # +inf upper bound
)

# Off-peak: 18 / 30 / 50
OFFPEAK_TIERS = (
    (100_000, 18),
    (250_000, 30),
    (None, 50),
)

TENANT_MULTIPLIER_ACTIVE = 1.0
TENANT_MULTIPLIER_SUSPENDED = 1.25

# Carry-forward credit blended rate — PRD §3.6
BLENDED_RATE_CENTS_PER_LITER = 25

# ---------------------------------------------------------------------------
# Alert severity — PRD §3.7
# ---------------------------------------------------------------------------
W_RULE = {
    "SENSOR_OFFLINE": 2,
    "ABNORMAL_FLOW": 3,
    "PIPE_BURST_SUSPICION": 5,
    "VALVE_FAULT": 4,
}
W_SUBJECT = {
    "SENSOR": 1,
    "PLOT": 2,
    "VALVE_GROUP": 3,
}
W_RECENT_ABNORMAL = 0.5

# Severity thresholds — PRD §3.7
SEVERITY_CRITICAL_THRESHOLD = 6.0   # >= 6.0 -> CRITICAL
SEVERITY_WARN_THRESHOLD = 3.0       # 3.0 <= s < 6.0 -> WARN; below -> INFO

# ---------------------------------------------------------------------------
# Alert reopen — PRD §3.7
# ---------------------------------------------------------------------------
ALERT_REOPEN_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Archival sweep — PRD §3.8 / §3.1
# ---------------------------------------------------------------------------
ARCHIVAL_SWEEP_HOURS = 24


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "SENSOR_POLL_INTERVAL_DEFAULT",
    "SENSOR_POLL_INTERVAL_MIN",
    "SENSOR_POLL_INTERVAL_MAX",
    "ABNORMAL_FLOW_CONSECUTIVE_THRESHOLD",
    "STAGE_BASE_LITERS_PER_HECTARE",
    "TARGET_MOISTURE_PCT",
    "RAINFALL_OFFSET_MM",
    "DEFAULT_MOISTURE_PCT_FALLBACK",
    "DEFAULT_RAINFALL_MM_FALLBACK",
    "QUOTA_WARNING_THRESHOLD_DEFAULT",
    "QUOTA_WARNING_THRESHOLD_MIN",
    "QUOTA_WARNING_THRESHOLD_MAX",
    "QUOTA_CARRY_FORWARD_CAP_PCT",
    "QUOTA_OVERRIDE_EXTRA_MAX_PCT",
    "PERCENTAGE_EPSILON",
    "VALVE_GROUP_VALVE_IDS_MAX_LENGTH",
    "PEAK_HOURS",
    "PEAK_TIERS",
    "OFFPEAK_TIERS",
    "TENANT_MULTIPLIER_ACTIVE",
    "TENANT_MULTIPLIER_SUSPENDED",
    "BLENDED_RATE_CENTS_PER_LITER",
    "W_RULE",
    "W_SUBJECT",
    "W_RECENT_ABNORMAL",
    "SEVERITY_CRITICAL_THRESHOLD",
    "SEVERITY_WARN_THRESHOLD",
    "ALERT_REOPEN_WINDOW_HOURS",
    "ARCHIVAL_SWEEP_HOURS",
]
