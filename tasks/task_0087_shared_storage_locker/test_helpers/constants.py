"""Domain thresholds and numeric constants from the PRD.

These constants encode numeric values the PRD pins to calculations
(insurance loading, capacity tiers, redistribution, time horizons).
"""
from __future__ import annotations


# PRD §2.11 — time horizons used by the sweep.
REMINDER_LEAD_MINUTES = 30
DEGRADED_THRESHOLD_MINUTES = 5
OFFLINE_THRESHOLD_MINUTES = 15

# PRD §3.4 — insurance premium constants.
BASIC_BASE_RATE_CENTS_PER_DAY = 50
PREMIUM_BASE_RATE_CENTS_PER_DAY = 150
BASIC_LOADING_RATE = 0.002
PREMIUM_LOADING_RATE = 0.005
LOADING_CAP_BASIC = 2000
LOADING_CAP_PREMIUM = 10000
DECLARED_VALUE_CAP_CENTS = 10_000_000

# PRD §3.4 — Hour/day conversion constants used by overdue + insurance.
HOUR_SECONDS = 3600
DAY_SECONDS = 86400
MONTH_DAYS = 30

# PRD §3.7 — capacity alert thresholds. Boundary uses `>=`.
WARNING_PCT = 80.0
CRITICAL_PCT = 95.0

# PRD §3.7 — redistribution suggestion.
REDISTRIBUTION_RADIUS_KM = 5.0
DISTANCE_WEIGHT = 10.0
OCC_WEIGHT = 1.0
EARTH_RADIUS_KM = 6371.0


# Sensible defaults for fixture factories.
TEST_DEFAULTS = {
    "PARTNER_SHARE_PCT": 30,
    "UNIT_PRICE_CENTS_HOURLY": 500,
    "UNIT_PRICE_CENTS_DAILY": 500,
    "DEPOSIT_CENTS": 2000,
    "GRACE_MINUTES": 15,
    "OVERDUE_RATE_CENTS_PER_HOUR": 200,
    "FORCED_CLEARANCE_HOURS": 48,
    "LATITUDE": 39.9042,
    "LONGITUDE": 116.4074,
}


__all__ = [
    "REMINDER_LEAD_MINUTES",
    "DEGRADED_THRESHOLD_MINUTES",
    "OFFLINE_THRESHOLD_MINUTES",
    "BASIC_BASE_RATE_CENTS_PER_DAY",
    "PREMIUM_BASE_RATE_CENTS_PER_DAY",
    "BASIC_LOADING_RATE",
    "PREMIUM_LOADING_RATE",
    "LOADING_CAP_BASIC",
    "LOADING_CAP_PREMIUM",
    "DECLARED_VALUE_CAP_CENTS",
    "HOUR_SECONDS",
    "DAY_SECONDS",
    "MONTH_DAYS",
    "WARNING_PCT",
    "CRITICAL_PCT",
    "REDISTRIBUTION_RADIUS_KM",
    "DISTANCE_WEIGHT",
    "OCC_WEIGHT",
    "EARTH_RADIUS_KM",
    "TEST_DEFAULTS",
]
