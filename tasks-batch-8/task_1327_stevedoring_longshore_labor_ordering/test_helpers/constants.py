"""Domain thresholds — numeric constants pinned by the PRD (§3.4-§3.9)."""

THRESHOLDS = {
    # Payroll (PRD §3.8)
    "OT_START_MINUTES": 480,
    "DT_START_MINUTES": 720,
    "MEAL_THRESHOLD_MINUTES": 300,
    "MEAL_PENALTY_MINUTES": 60,
    "TIMESHEET_GRACE_MINUTES": 120,
    # Shift windows (PRD §3.1)
    "SHIFT_MAX_DURATION_MINUTES": 960,
    # Equipment turnaround (PRD §3.4)
    "EQUIPMENT_BUFFER_MINUTES": 30,
    # Damage claims (PRD §3.7)
    "PROVISIONAL_SHARE_PCT": 50,
    "STEVEDORE_CAP_CENTS": 25_000_000,
    "DEDUCTIBLE_CENTS": 50_000,
    # Productivity bonus (PRD §3.5)
    "BONUS_PER_EXCESS_MOVE_CENTS": 1500,
    # Invoice container tiers (PRD §3.9)
    "TIER1_MOVES": 500,
    "TIER1_RATE_CENTS": 4500,
    "TIER2_MOVES": 1000,
    "TIER2_RATE_CENTS": 4200,
    "TIER3_RATE_CENTS": 3900,
    "TON_RATE_CENTS": 620,
    "MANHOUR_RATE_CENTS": 6500,
    "STOPPAGE_CREDIT_PER_SUSPENSION_CENTS": 9000,
    "DISCOUNT_TIER1_SUBTOTAL_CENTS": 3_000_000,
    "DISCOUNT_TIER2_SUBTOTAL_CENTS": 6_000_000,
}

# Shift-period payroll multipliers (PRD §3.8)
PERIOD_MULTIPLIER = {"DAY": 1.00, "NIGHT": 1.10, "GRAVEYARD": 1.20}

# Equipment hourly billing rates in cents (PRD §3.9)
EQUIP_RATE_CENTS = {
    "SHIP_CRANE": 25_000,
    "RTG": 12_000,
    "FORKLIFT": 6_000,
    "TRACTOR": 5_500,
}

# Downed equipment bills at half rate (PRD §3.9)
DOWN_BILLING_FACTOR = 0.5

# Volume discount rates keyed on the pre-discount subtotal (PRD §3.9)
DISCOUNT_TIER1_RATE = 0.05
DISCOUNT_TIER2_RATE = 0.08

TEST_DEFAULTS = {
    "BASE_RATE_CENTS": 4000,
    "MPH_TARGET": 20.0,
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "SHIFT_DATE": "2026-08-10",
}
