"""Domain thresholds — numeric constants from the PRD's calculations and policy defaults."""

# Clock (PRD §2.4): server startup default
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

THRESHOLDS = {
    # Fill-timing window (PRD §3.6)
    "MIN_FILL_GAP_DAYS": 5,
    "MAX_FILL_WINDOW_DAYS": 21,
    # Sanitation coverage (PRD §3.2)
    "SANITATION_VALIDITY_HOURS": 12,
    # Patch test (PRD §3.3)
    "PATCH_TEST_VALIDITY_DAYS": 365,
    # Peak surcharge (PRD §3.9)
    "PEAK_LOAD_THRESHOLD": 3,
    "PEAK_SURCHARGE_PCT": 0.15,
    # Late cancel forfeiture (PRD §3.8)
    "LATE_CANCEL_FORFEIT_RATE": 0.50,
    # Premium skill floor (PRD §3.7)
    "PREMIUM_MIN_SKILL_LEVEL": 2,
}

# Studio policy defaults (PRD §3.1)
STUDIO_DEFAULTS = {
    "deposit_rate_pct": 0.20,
    "late_cancel_cutoff_hours": 24,
    "noshow_strike_window_days": 90,
    "noshow_strike_threshold": 3,
}

# Plan defaults (PRD §3.1)
PLAN_DEFAULTS = {
    "rollover_cap_multiplier": 1.0,
    "loyalty_discount_pct": 0.10,
}
