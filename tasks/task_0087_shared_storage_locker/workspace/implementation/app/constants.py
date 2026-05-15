"""Domain-wide constants — values are pinned by the PRD/scaffold."""
from __future__ import annotations


# Rental duration units (seconds)
HOUR_SECONDS = 3600
DAY_SECONDS = 86400
MONTH_DAYS = 30

# Reminder lead time (minutes before current_expires_at → EXPIRING_SOON)
REMINDER_LEAD_MINUTES = 30

# Heartbeat thresholds (minutes)
DEGRADED_THRESHOLD_MINUTES = 5
OFFLINE_THRESHOLD_MINUTES = 15

# Holding window for force-cleared compartments (hours)
HOLDING_CLAIM_WINDOW_HOURS = 72

# Capacity alert thresholds (percent)
WARNING_PCT = 80.0
CRITICAL_PCT = 95.0

# Redistribution suggestion
REDISTRIBUTION_RADIUS_KM = 5.0
DISTANCE_WEIGHT = 10.0
OCC_WEIGHT = 1.0
EARTH_RADIUS_KM = 6371.0

# Insurance constants
BASIC_BASE_RATE_CENTS_PER_DAY = 50
PREMIUM_BASE_RATE_CENTS_PER_DAY = 150
BASIC_LOADING_RATE = 0.002
PREMIUM_LOADING_RATE = 0.005
LOADING_CAP_BASIC = 2000
LOADING_CAP_PREMIUM = 10000
DECLARED_VALUE_CAP_CENTS = 10_000_000

# Tier payout caps (used at claim approval).
# Pin these to match the loading caps so the comparison stays meaningful — the spec
# defines a per-tier "TIER_PAYOUT_CAP" without a concrete number; we keep it at
# declared-value-cap as a conservative ceiling, falling back to declared_value_cents.
TIER_PAYOUT_CAP = {
    "BASIC": DECLARED_VALUE_CAP_CENTS,
    "PREMIUM": DECLARED_VALUE_CAP_CENTS,
}

# Enums
SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}
RENTAL_MODES = {"HOURLY", "DAILY", "MONTHLY"}
UNLOCK_CHANNELS = {"QR", "BLUETOOTH", "PASSWORD"}
INSURANCE_TIERS = {"NONE", "BASIC", "PREMIUM"}
FAULT_CATEGORIES = {"DOOR_NOT_CLOSED", "SENSOR_FAULT", "COMMUNICATION_LOSS", "USER_REPORTED"}
CLAIM_TYPES = {"DAMAGE", "LOSS", "THEFT"}


def unit_duration_seconds(rental_mode: str) -> int:
    if rental_mode == "HOURLY":
        return HOUR_SECONDS
    if rental_mode == "DAILY":
        return DAY_SECONDS
    if rental_mode == "MONTHLY":
        return MONTH_DAYS * DAY_SECONDS
    raise ValueError(f"Unknown rental_mode: {rental_mode!r}")
