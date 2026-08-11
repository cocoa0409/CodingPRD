"""Domain thresholds — numeric constants from PRD calculations and rules."""

THRESHOLDS = {
    # Medicaid acuity pricing (PRD §3.7)
    "NURSING_HOURLY_CENTS": 1500,
    "NURSING_WEEKLY_CAP_CENTS": 9000,
    "DAYS_PER_WEEK": 7,
    "LOW_ADL_MAX": 2,
    "HIGH_ADL_MIN": 5,
    "LOW_NURSING_HOURS_MAX_EXCLUSIVE": 5,
    "HIGH_NURSING_HOURS_MIN": 15,
    # Late fee (PRD §3.8)
    "LATE_FEE_RATE_NUMERATOR": 5,
    "LATE_FEE_RATE_DENOMINATOR": 100,
    "LATE_FEE_MIN_CENTS": 2500,
    "LATE_FEE_MAX_CENTS": 15000,
    # Staffing (PRD §3.5)
    "DAY_RATIO_DENOMINATOR": 4,
    "AWAKE_OVERNIGHT_RATIO_DENOMINATOR": 2,
    "MIXED_OVERNIGHT_RATIO_DENOMINATOR": 3,
    "MAX_SHIFT_HOURS": 16,
    "MAX_HOURS_PER_ROLLING_24H": 16,
    # Medication window (PRD §3.4)
    "MED_WINDOW_BEFORE_MINUTES": 60,
    "MED_WINDOW_AFTER_MINUTES": 60,
    # Incident reporting deadline (PRD §3.6)
    "REPORT_DEADLINE_HOURS": 24,
    # Compliance (PRD §3.6)
    "CORRECTION_PLAN_DUE_DAYS": 14,
    # Discharge notice (PRD §3.8)
    "DISCHARGE_NOTICE_DAYS": 30,
    # Home license bounds (PRD §3.1)
    "LICENSED_BED_CAPACITY_MIN": 2,
    "LICENSED_BED_CAPACITY_MAX": 6,
}

TEST_DEFAULTS = {
    "TIMEZONE": "America/Los_Angeles",
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
    "SETUP_CLOCK": "2026-05-20T00:00:00Z",
    "ROOM_AND_BOARD_DAILY_CENTS": 12000,
    "CARE_LOW_DAILY_CENTS": 3000,
    "CARE_MEDIUM_DAILY_CENTS": 6000,
    "CARE_HIGH_DAILY_CENTS": 9000,
}

# Sentinel identifiers used across tests
PROVIDER_1_USER_ID = "prov-1"   # admission creator (segregation of duties)
PROVIDER_2_USER_ID = "prov-2"   # admission approver (different operator)
SYSTEM_DECIDER = "system"       # recorded as decided_by on forced rejections
