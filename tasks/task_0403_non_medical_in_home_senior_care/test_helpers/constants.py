"""Domain thresholds and default configuration values from the PRD.

These mirror the agency configuration defaults (PRD section 3.1) and the
continuity-score weighting (PRD section 3.7).
"""

# Agency configuration defaults (PRD section 3.1).
AGENCY_DEFAULTS = {
    "base_hourly_rate": 30.00,
    "live_in_day_rate": 250.00,
    "overtime_threshold_hours": 40,
    "overtime_multiplier": 1.5,
    "mileage_rate": 0.70,
    "evv_rounding_minutes": 15,
    "travel_buffer_minutes": 30,
}

# Caregiver default cap (PRD section 3.2).
DEFAULT_MAX_WEEKLY_HOURS = 50

# Continuity-score weighting (PRD section 3.7).
CONTINUITY_WEIGHT = 0.6
RELIABILITY_WEIGHT = 0.4

# Minutes per started live-in day block (PRD section 3.6).
MINUTES_PER_DAY = 1440
