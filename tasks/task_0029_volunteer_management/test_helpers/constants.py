"""Domain thresholds — numeric constants from PRD calculations.

Sourced from PRD §2.3 (pagination), §2.5 (precision), §3.4 (distance and
quota), §3.5 (15-min markers and 0.50 km check-in), §3.6 (penalty
multipliers), §3.7 (point calculation factors), §3.8 (archive/expiry).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Geography (PRD §3.4 distance threshold; §3.5 check-in proof radius)
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0088
DISTANCE_LIMIT_KM = 50.0
CHECK_IN_GPS_RADIUS_KM = 0.50  # 500 m
LATITUDE_MIN = -90.0
LATITUDE_MAX = 90.0
LONGITUDE_MIN = -180.0
LONGITUDE_MAX = 180.0


# ---------------------------------------------------------------------------
# Time markers (PRD §3.5)
# ---------------------------------------------------------------------------
LATE_MARKER_THRESHOLD_MINUTES = 15
EARLY_DEPARTURE_THRESHOLD_MINUTES = 15


# ---------------------------------------------------------------------------
# Hour calculation penalties (PRD §3.6)
# ---------------------------------------------------------------------------
LEAVE_PENALTY_MULTIPLIER = 0.50
EARLY_DEPARTURE_PENALTY_MULTIPLIER = 0.75


# ---------------------------------------------------------------------------
# Point earning factors (PRD §3.7)
# ---------------------------------------------------------------------------
HOURS_TO_POINTS = 10

DIFFICULTY_MULTIPLIERS = {
    "EASY": 1.00,
    "MEDIUM": 1.50,
    "HARD": 2.00,
}

ROLE_MULTIPLIERS = {
    "LEAD": 1.20,
    "SUPPORT": 1.00,
    "REGULAR": 0.90,
}
DEFAULT_ROLE_MULTIPLIER = 1.00  # When no ActivityRole assigned (PRD §3.7)


# ---------------------------------------------------------------------------
# Sweeps (PRD §3.8)
# ---------------------------------------------------------------------------
ARCHIVE_AGE_DAYS = 365
POINT_EXPIRY_DAYS = 730


# ---------------------------------------------------------------------------
# Field-level constraints (PRD §3.x)
# ---------------------------------------------------------------------------
FULL_NAME_MIN = 1
FULL_NAME_MAX = 100

ACTIVITY_TITLE_MIN = 1
ACTIVITY_TITLE_MAX = 120
ACTIVITY_DESCRIPTION_MIN = 1
ACTIVITY_DESCRIPTION_MAX = 2000

POSITION_QUOTA_MIN = 1
POSITION_QUOTA_MAX = 1000

FIXED_HOUR_VALUE_MIN = 0.25
FIXED_HOUR_VALUE_MAX = 24.0

ACTIVITY_ROLE_LABEL_MIN = 1
ACTIVITY_ROLE_LABEL_MAX = 40
COEFFICIENT_MIN = 0.5
COEFFICIENT_MAX = 3.0

LEAVE_REASON_MIN = 1
LEAVE_REASON_MAX = 500

DELTA_HOURS_MIN = -8.0
DELTA_HOURS_MAX = 8.0
ADJUSTMENT_REASON_MIN = 10
ADJUSTMENT_REASON_MAX = 500

SKU_MIN = 2
SKU_MAX = 40
POINT_COST_MIN = 1
POINT_COST_MAX = 100_000
QUANTITY_MIN = 1
QUANTITY_MAX = 10

CERT_TEMPLATE_CODE_MIN = 2
CERT_TEMPLATE_CODE_MAX = 40
SERIAL_NUMBER_LENGTH = 12
SITE_CODE_LENGTH = 6

SKILL_CODE_MIN = 2
SKILL_CODE_MAX = 40


# ---------------------------------------------------------------------------
# Logical clock baseline (PRD §2.11)
# ---------------------------------------------------------------------------
CLOCK_BASELINE_ISO = "2030-03-01T08:00:00.000Z"


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "EARTH_RADIUS_KM",
    "DISTANCE_LIMIT_KM",
    "CHECK_IN_GPS_RADIUS_KM",
    "LATITUDE_MIN",
    "LATITUDE_MAX",
    "LONGITUDE_MIN",
    "LONGITUDE_MAX",
    "LATE_MARKER_THRESHOLD_MINUTES",
    "EARLY_DEPARTURE_THRESHOLD_MINUTES",
    "LEAVE_PENALTY_MULTIPLIER",
    "EARLY_DEPARTURE_PENALTY_MULTIPLIER",
    "HOURS_TO_POINTS",
    "DIFFICULTY_MULTIPLIERS",
    "ROLE_MULTIPLIERS",
    "DEFAULT_ROLE_MULTIPLIER",
    "ARCHIVE_AGE_DAYS",
    "POINT_EXPIRY_DAYS",
    "FULL_NAME_MIN",
    "FULL_NAME_MAX",
    "ACTIVITY_TITLE_MIN",
    "ACTIVITY_TITLE_MAX",
    "ACTIVITY_DESCRIPTION_MIN",
    "ACTIVITY_DESCRIPTION_MAX",
    "POSITION_QUOTA_MIN",
    "POSITION_QUOTA_MAX",
    "FIXED_HOUR_VALUE_MIN",
    "FIXED_HOUR_VALUE_MAX",
    "ACTIVITY_ROLE_LABEL_MIN",
    "ACTIVITY_ROLE_LABEL_MAX",
    "COEFFICIENT_MIN",
    "COEFFICIENT_MAX",
    "LEAVE_REASON_MIN",
    "LEAVE_REASON_MAX",
    "DELTA_HOURS_MIN",
    "DELTA_HOURS_MAX",
    "ADJUSTMENT_REASON_MIN",
    "ADJUSTMENT_REASON_MAX",
    "SKU_MIN",
    "SKU_MAX",
    "POINT_COST_MIN",
    "POINT_COST_MAX",
    "QUANTITY_MIN",
    "QUANTITY_MAX",
    "CERT_TEMPLATE_CODE_MIN",
    "CERT_TEMPLATE_CODE_MAX",
    "SERIAL_NUMBER_LENGTH",
    "SITE_CODE_LENGTH",
    "SKILL_CODE_MIN",
    "SKILL_CODE_MAX",
    "CLOCK_BASELINE_ISO",
]
