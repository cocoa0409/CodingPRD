"""Domain thresholds — numeric constants from the PRD calculations and defaults."""

# Risk-score weights and tier bands (PRD 3.2).
RISK_WEIGHTS = {
    "W_ED": 2,
    "W_CHRONIC": 3,
    "W_ADMIT": 5,
}
RISK_TIER_BANDS = {
    "MOD_MIN": 10,   # score >= 10 and < 20 => MODERATE
    "HIGH_MIN": 20,  # score >= 20 => HIGH
}

# Readmission window (PRD 3.2): inclusive upper bound of 30 whole days.
READMISSION_WINDOW_DAYS = 30

# Telehealth patient buffer (PRD 3.5): 15 minutes.
TELEHEALTH_BUFFER_MINUTES = 15

# Default logical-clock instant before any call (PRD 2.5).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Standard program economic configuration reused across setups.
DEFAULT_PROGRAM = {
    "budget_cap_cents": 1_000_000,
    "enrollment_cap": 10,
    "per_visit_rate_cents": 15_000,
    "per_telehealth_rate_cents": 8_000,
    "diversion_bonus_cents": 50_000,
    "readmission_penalty_cents": 30_000,
    "diversion_target_max_ed_visits": 1,
    "avg_ed_cost_cents": 124_700,
    "diversion_credit_pct": 0.855,
    "start_date": "2026-01-01T00:00:00Z",
    "end_date": "2027-01-01T00:00:00Z",
}
