"""Domain thresholds and shared values — numeric constants from the PRD."""

# Startup reading of the logical clock (PRD: the logical clock section).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Annual plan-fee base rates by system category, in cents (PRD plan-fee section).
BASE_FEE_CENTS = {
    "FIRE_ALARM": 120000,
    "SPRINKLER": 180000,
    "BACKFLOW": 9000,
    "FIRE_PUMP": 240000,
}

# Device-type -> inspection frequency code table (PRD device section).
DEVICE_FREQUENCY = {
    "FIRE_PUMP_CONTROLLER": "MONTHLY",
    "GAUGE_VALVE": "QUARTERLY",
    "SUPERVISORY_SWITCH": "QUARTERLY",
    "SMOKE_DETECTOR": "ANNUAL",
    "PULL_STATION": "ANNUAL",
    "NOTIFICATION_APPLIANCE": "ANNUAL",
    "SPRINKLER_HEAD": "ANNUAL",
    "BACKFLOW_ASSEMBLY": "ANNUAL",
}

# Interval in calendar months per frequency code (PRD device section).
FREQUENCY_INTERVAL_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}

# Required inspection events per plan year by frequency (PRD plan section).
EVENTS_PER_FREQUENCY = {"MONTHLY": 12, "QUARTERLY": 4, "ANNUAL": 1}

# System-category -> required license class mapping (PRD event-start section).
CATEGORY_LICENSE_CLASS = {
    "FIRE_ALARM": "ALARM",
    "SPRINKLER": "SPRINKLER",
    "BACKFLOW": "BACKFLOW",
    "FIRE_PUMP": "PUMP",
}

THRESHOLDS = {
    # Compliance score (PRD scoring section).
    "SCORE_START": 1000,
    "SUSPEND_SCORE_LT": 600,
    "PROBATION_SCORE_LT": 850,
    "SUSPEND_CRITICAL_GTE": 3,
    "PROBATION_CRITICAL_GTE": 1,
    "DEDUCT_CRITICAL_OVERDUE": 40,
    "DEDUCT_NONCRITICAL_OVERDUE": 10,
    "DEDUCT_LATE_REPORT": 25,
    "DEDUCT_LATE_IMPAIRMENT_NOTICE": 60,
    "DEDUCT_NEGLIGENCE_ALARM": 15,
    "DEDUCT_FAILED_SPECIALTY_TEST": 30,
    "DEDUCT_LAPSED_PLAN": 75,
    "DEDUCT_NO_ACCESS": 20,
    "DEDUCT_WAIVER": 5,
    "DEDUCT_UNPERMITTED_WORK": 100,
    "AUDIT_ONTIME_EVENT_BONUS": 2,
    "AUDIT_BONUS_CAP": 50,
    "AUDIT_LICENSE_DEDUCTION": 100,
    "AUDIT_WINDOW_DAYS": 90,
    # Deficiency late fees (PRD deficiency section).
    "CRITICAL_LATE_PER_DAY_CENTS": 20000,
    "NONCRITICAL_LATE_PER_DAY_CENTS": 5000,
    "LATE_FEE_CAP_DAYS": 30,
    "EXTENSION_DAYS": 30,
    # Marshal report submission window, in calendar days (PRD report section).
    "MARSHAL_REPORT_WINDOW_DAYS": 7,
    # Impairment escalation / notification windows (PRD impairment section).
    "IMPAIRMENT_OUT_OF_SERVICE_HOURS": 10,
    "PLANNED_NOTIFY_LEAD_HOURS": 8,
    "UNPLANNED_NOTIFY_LAG_HOURS": 2,
    "IMPAIRMENT_BUFFER_HOURS": 4,
    # False-alarm fee schedule (PRD false-alarm section).
    "FA_TIER3_4_CENTS": 15000,
    "FA_TIER5_6_CENTS": 30000,
    "FA_TIER7P_CENTS": 50000,
    "FA_HABITUAL_SURCHARGE_CENTS": 25000,
    "FA_WINDOW_DAYS": 365,
    "FA_WINDOW_LOOKBACK_DAYS": 364,
    # Backflow billing (PRD backflow section).
    "BACKFLOW_TEST_FEE_CENTS": 40000,
    "BACKFLOW_PAYMENT_DUE_DAYS": 30,
    "BACKFLOW_MONTHLY_COMPOUND_RATE": 0.05,
    # Permit fees and validity (PRD permit section).
    "PERMIT_TIER1_CAP_CENTS": 200000,
    "PERMIT_TIER2_CAP_CENTS": 300000,
    "MIN_PERMIT_FEE_CENTS": 7500,
    "PERMIT_VALIDITY_DAYS": 90,
    # Technician aggregate capacity: at most three overlapping engagements.
    "TECHNICIAN_MAX_OVERLAPPING_EVENTS": 3,
}
