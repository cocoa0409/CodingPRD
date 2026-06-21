"""Domain thresholds derived from PRD calculations."""

# Full estate is exactly 10000 basis points (PRD §2.7).
TOTAL_BASIS_POINTS = 10000

# Creditor window: 120 days from probate_opened_at, strict > rejected (PRD §3.6).
CREDITOR_WINDOW_DAYS = 120

# Ward eligibility: ward_date_of_birth + 18 years must be > date_of_death (PRD §3.3).
ADULT_AGE_YEARS = 18

# Probate-order supersede cascade window: 72 hours (PRD §3.7).
CONTEST_SUPERSEDE_WINDOW_HOURS = 72

# Per-state intestacy shares (PRD §3.7). Used by reference values.
STATE_INTESTACY_SHARES = {
    "CA": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "NY": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "TX": {"spouse_first_bp": 3333, "child_pool_bp": 6667},
    "FL": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
    "IL": {"spouse_first_bp": 5000, "child_pool_bp": 5000},
}
