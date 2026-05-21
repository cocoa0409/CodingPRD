"""Domain thresholds — numeric constants from PRD calculations.

Every constant below is taken verbatim from a §2.5, §2.6, §3.3, §3.4,
§3.5, or §3.6 narrative in the PRD. Tests use these by symbolic name so
the boundary intent is visible.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Surge formula — PRD §2.5.
# ---------------------------------------------------------------------------
MULTIPLIER_CAP = 3.00                 # PRD §2.5 "MULTIPLIER_CAP of 3.00".
AIRPORT_SURCHARGE = 0.50              # PRD §2.5 "AIRPORT_SURCHARGE of 0.50".
MIN_MULTIPLIER = 1.00                 # PRD §3.1 "constrained to lie between 1.00 and ... inclusive".

# Tiered ratio thresholds — PRD §2.5: "a ratio less than or equal to
# 1.0 yields a raw multiplier of 1.00; greater than 1.0 and less than or
# equal to 2.0 yields 1.50; greater than 2.0 and less than or equal to
# 3.0 yields 2.00; greater than 3.0 and less than or equal to 4.0 yields
# 2.50; strictly greater than 4.0 yields the MULTIPLIER_CAP of 3.00."
SURGE_TIER_THRESHOLDS = [
    (1.0, 1.00),
    (2.0, 1.50),
    (3.0, 2.00),
    (4.0, 2.50),
]
SURGE_ABOVE_TOP = 3.00                # ratio > 4.0 → 3.00


# ---------------------------------------------------------------------------
# Fare formula — PRD §3.3 (quoted) and §3.4 (final).
# ---------------------------------------------------------------------------
BASE_FARE_CENTS = 250                 # PRD §3.3 "BASE_FARE_CENTS (250)".
PER_KM_CENTS = 120                    # PRD §3.3 "PER_KM_CENTS (120)".
PLATFORM_FEE_RATE = 0.20              # PRD §3.4 "platform's fee rate, PLATFORM_FEE_RATE, is 0.20".


# ---------------------------------------------------------------------------
# Rush-hour window — PRD §3.5.
# ---------------------------------------------------------------------------
RUSH_HOUR_MIN_MINUTE = 0
RUSH_HOUR_MAX_MINUTE = 1440           # exclusive upper bound on end_minute.
RUSH_HOUR_MIN_BONUS = 0.00
RUSH_HOUR_MAX_BONUS = 1.00


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Day-of-week values — PRD §3.5.
# ---------------------------------------------------------------------------
DAYS_OF_WEEK = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


# ---------------------------------------------------------------------------
# Convenience defaults for factories.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "GRID_NAME": "Test Grid",
    "DRIVER_NAME": "Test Driver",
    "RIDER_NAME": "Test Rider",
    "DISTANCE_KM": 5.0,
    "REASON_CODE": "OVERCHARGE",
}


__all__ = [
    "AIRPORT_SURCHARGE",
    "BASE_FARE_CENTS",
    "DAYS_OF_WEEK",
    "MIN_MULTIPLIER",
    "MULTIPLIER_CAP",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "PER_KM_CENTS",
    "PLATFORM_FEE_RATE",
    "RUSH_HOUR_MAX_BONUS",
    "RUSH_HOUR_MAX_MINUTE",
    "RUSH_HOUR_MIN_BONUS",
    "RUSH_HOUR_MIN_MINUTE",
    "SURGE_ABOVE_TOP",
    "SURGE_TIER_THRESHOLDS",
    "TEST_DEFAULTS",
]
