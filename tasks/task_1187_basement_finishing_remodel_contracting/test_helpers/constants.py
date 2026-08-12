"""Domain thresholds — numeric constants from the PRD's calculation rules (§3)."""

THRESHOLDS = {
    # Moisture risk scoring (PRD §3.2)
    "SCREEN_SLAB_T1": 3.0,
    "SCREEN_SLAB_T2": 5.0,
    "SCREEN_RH_T1": 60,
    "SCREEN_RH_T2": 70,
    "VERIF_SLAB_T1": 2.0,
    "VERIF_SLAB_T2": 4.0,
    "VERIF_RH_T1": 55,
    "VERIF_RH_T2": 65,
    "EFFLORESCENCE_POINTS": 20,
    "GRADING_POINTS": 15,
    # Permit egress / ceiling compliance (PRD §3.4)
    "EGRESS_NET_CLEAR_MIN_SQFT": 5.7,
    "EGRESS_SILL_MAX_IN": 44,
    "CEILING_FULL_HEIGHT_IN": 84,
    "CEILING_MIN_HABITABLE_IN": 76,
    "PERMIT_VALID_DAYS": 180,
    # Change-order pricing and project price (PRD §3.5)
    "MARKUP_PCT": 0.15,
    "CONTINGENCY_PCT": 0.10,
    # Work-phase scheduling (PRD §3.6)
    "DRYWALL_BUFFER_DAYS": 2,
    "MAX_DAILY_CREW": 4,
    # Site discipline / strike system (PRD §3.7)
    "NOISE_DB_LIMIT": 65,
    "STRIKE_WINDOW_DAYS": 14,
    "STRIKE_SUSPEND_THRESHOLD": 3,
    # Warranty coverage (PRD §3.9)
    "FULL_COVERAGE_DAYS": 365,
    "WARRANTY_TERM_DAYS": 730,
    "RECURRENCE_DELTA_LBS": 1.5,
    "MAX_AWARD_CENTS": 200000,
}

TEST_DEFAULTS = {
    "BASE_CONTRACT_CENTS": 4_000_000,
    "BASEMENT_SQFT": 800,
    "ALLOWANCE_BUDGET_CENTS": 100_000,
}

# The logical clock reads exactly this instant before any adjustment (PRD §2.5).
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"
