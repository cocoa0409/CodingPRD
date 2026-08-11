"""Domain thresholds and fee-schedule constants (PRD §3.1–§3.9)."""

# Logical clock boot instant (PRD §2.8)
CLOCK_BOOT_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Posture boundary, inclusive: outstanding >= 10000 cents -> SUSPENDED (PRD §3.2)
    "SUSPEND_THRESHOLD_CENTS": 10000,
    # Appeal window (PRD §3.7)
    "APPEAL_WINDOW_DAYS": 30,
    # Declare-lost requires assignment OVERDUE >= 30 days (PRD §3.5)
    "DECLARE_LOST_OVERDUE_DAYS": 30,
    # Loaner escalation requires OVERDUE >= 7 days (PRD §3.8)
    "LOANER_ESCALATE_OVERDUE_DAYS": 7,
    # Fee write-off requires >= 180 days in ASSESSED (PRD §3.7)
    "FEE_WRITE_OFF_AGE_DAYS": 180,
    # Default loaner duration cap (PRD §3.8)
    "DEFAULT_MAX_LOANER_DAYS": 14,
    # Default loaner pool reserve fraction (PRD §3.1)
    "DEFAULT_LOANER_POOL_THRESHOLD_PCT": 0.10,
}

# Late-return tiered daily schedule, boundaries inclusive on the lower edge (PRD §3.5)
LATE_FEE = {
    "TIER1_MAX_DAY": 7,
    "TIER1_DAILY_CENTS": 100,
    "TIER2_MAX_DAY": 30,
    "TIER2_DAILY_CENTS": 250,
    "TIER3_DAILY_CENTS": 500,
    # Free-lunch late fees are halved, rounded half up (PRD §3.5)
    "LATE_WAIVER_RATE": 0.50,
}

# Damage fee schedule (PRD §3.6)
DAMAGE_FEE = {
    "SEVERITY_MULTIPLIER": {
        "COSMETIC": 0.10,
        "FUNCTIONAL": 0.45,
        "LIQUID": 0.80,
        "SCREEN": 0.55,
        "LOSS": 1.00,
        "THEFT": 1.00,
    },
    "CONDITION_DISCOUNT": {"A": 0.00, "B": 0.10, "C": 0.25, "D": 0.50, "F": 0.75},
    # Free-lunch damage waiver rate (PRD §3.6 step 3)
    "DAMAGE_WAIVER_RATE": 0.80,
}

# Depreciation (PRD §3.1): elapsed days / 30.44, rounded down, capped at useful life
DEPRECIATION = {"DAYS_PER_MONTH": 30.44}

TEST_DEFAULTS = {
    "REPLACEMENT_COST_CENTS": 100000,
    "SALVAGE_VALUE_CENTS": 10000,
    "USEFUL_LIFE_MONTHS": 36,
    "IN_SERVICE_DATE": "2025-09-01T00:00:00Z",
}
