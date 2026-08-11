"""Domain thresholds — numeric constants from PRD calculations."""

# work_rank_score (PRD §3.1)
RANK = {
    "RISK_WEIGHT": {"A": 5, "B": 3, "C": 1},
    "DOWNSTREAM_WEIGHT": 25,
    "COST_TERM_CAP": 500,
    "COST_TERM_DIVISOR": 10000,
}

# shift_labor_cost (PRD §3.8)
LABOR = {
    "BASE_RATE_CENTS": 8500,
    "OT1_MULT": 1.5,
    "OT2_MULT": 2.0,
    "NIGHT_MULT": 1.20,
    "HAZARD_MULT": 1.15,
    "DAILY_CAP_CENTS": 250000,
}

# overhead_allocation (PRD §3.8)
OVERHEAD = {
    "TIER_THRESHOLD_CENTS": 200000,
    "PCT": {"LOW": 0.10, "HIGH": 0.15},
}

# eac_cost_forecast (PRD §3.8)
EAC = {
    "HOURS_PER_SLIP_DAY": 8,
    "DAILY_OVERHEAD_CENTS": 50000,
}

# fatigue_eligibility (PRD §3.3)
FATIGUE = {
    "MIN_REST_HOURS": 10,
    "RECOVERY_REST_HOURS": 14,
    "REST_PENALTY": 10,
    "NIGHT_PENALTY": 5,
    "FATIGUE_SCORE_LIMIT": 20,
    "FATIGUE_HOURS_LIMIT": 60,
}

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
