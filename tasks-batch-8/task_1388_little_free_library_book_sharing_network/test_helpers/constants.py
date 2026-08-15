"""Domain thresholds — numeric constants from the PRD's calculation rules."""

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Recognition tiers (inclusive lower bounds on rolling_points)
    "BRONZE_MIN": 100,
    "SILVER_MIN": 300,
    "GOLD_MIN": 600,
    "PLATINUM_MIN": 1000,
    "ROLLING_WINDOW_DAYS": 365,
    # Listing posture
    "UPHELD_WINDOW_DAYS": 90,
    "UPHELD_DELIST_THRESHOLD": 3,
    "UPHELD_FLAG_THRESHOLD": 1,
    "STALE_FLAG_DAYS": 120,
    "STALE_DELIST_DAYS": 180,
    # Sweep-driven timers
    "SUSPENDED_DECOMMISSION_DAYS": 30,
    "QUARANTINE_RECYCLE_DAYS": 30,
    "INSPECTION_MIN_GAP_DAYS": 30,
    "REOPEN_WINDOW_DAYS": 14,
    "RESPONSE_WINDOW_HOURS": 72,
    # Repair SLA base hours per severity
    "SLA_LOW_HOURS": 336,
    "SLA_MEDIUM_HOURS": 168,
    "SLA_HIGH_HOURS": 72,
    "SLA_CRITICAL_HOURS": 24,
    "WINTER_MULTIPLIER": 2.0,
    "DEFAULT_MULTIPLIER": 1.0,
    # Parts reimbursement
    "PARTS_RATE": 0.8,
    "LABOR_RATE_CENTS_PER_HOUR": 500,
    "MAX_REIMBURSEMENT_CENTS": 15000,
    # Distribution selector
    "PER_BOX_QTY_CAP": 10,
    "STALENESS_CAP_DAYS": 60,
    "REGION_MATCH_BONUS": 20,
    "NEED_PER_BOOK": 2,
    # Drive fulfillment
    "BONUS_THRESHOLD_PCT": 80,
    # Training
    "PASS_SCORE": 80,
}

# Signed recognition points per event type.
POINTS = {
    "MAINTENANCE_RESOLVED": 40,
    "ALLOCATION_PLACED": 5,
    "DRIVE_COMPLETED_BONUS": 150,
    "DRIVE_COMPLETED_BASE": 50,
    "COMPLAINT_UPHELD": -60,
    "COMPLAINT_UPHELD_COMPENSATION": 60,
    "TRAINING_PASSED": 25,
}

# Box capacity limit per recognition tier.
BOX_LIMITS = {
    "NONE": 1,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "PLATINUM": 5,
}

# Pinned operator identities used across tests (opaque roles).
ADMIN_1 = "admin-1"
ADMIN_2 = "admin-2"
MOD_1 = "mod-1"
MOD_2 = "mod-2"
MOD_3 = "mod-3"
HUB_1 = "hub-1"
