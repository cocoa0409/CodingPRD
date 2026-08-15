"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Downtime billing (PRD §3.5)
    "GRACE_MINUTES": {
        "CUSTOMER_DELAY": 30,
        "WEATHER": 60,
        "REGULATORY_HOLD": 0,
        "SAFETY_STOP": 0,
        "CONTRACTOR_FAULT": 0,
    },
    "DAILY_CAP_MINUTES": 480,
    "BILLING_BLOCK_MINUTES": 15,
    # Containment (PRD §3.4)
    "MIN_CAPTURE_RATIO": 0.95,
    # T&M regular-hours split (PRD §3.7)
    "REGULAR_HOURS_PER_ASSIGNMENT": 8.0,
    # Volume discount tiers (PRD §3.7)
    "TIER1_THRESHOLD_CENTS": 500000,
    "TIER1_PCT": 0.03,
    "TIER2_THRESHOLD_CENTS": 2000000,
    "TIER2_PCT": 0.07,
    "ENV_FEE_PCT": 0.02,
    # Manifest variance exception threshold (PRD §3.6)
    "EXCEPTION_THRESHOLD_PCT": 10.00,
    # Operator rest buffer (PRD §3.2)
    "OPERATOR_REST_HOURS": 10,
}

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_RENDERED = "2026-08-01T00:00:00.000Z"

TEST_DEFAULTS = {
    "VACUUM_RATE": 250,
    "HYDRO_RATE": 1800,
    "LABOR_RATE": 14500,
    "EQUIPMENT_RATE": 22000,
    "STANDBY_RATE": 12000,
    "OT_MULTIPLIER": 1.5,
    "MINIMUM_INVOICE": 75000,
}

# Standard role user ids used by design-index setup chains.
USER_IDS = {
    "fs": "fs_1",
    "sm": "sm_1",
    "co": "co_1",
    "ea": "ea_1",
    "pm": "pm_1",
    "am": "am_1",
    "pa": "pa_1",
}
