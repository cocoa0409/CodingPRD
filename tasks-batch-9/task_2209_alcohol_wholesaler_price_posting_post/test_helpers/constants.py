"""Domain thresholds and default configuration values stated in the PRD."""

# Logical clock position at server start-up (PRD §2.4).
CLOCK_START_UTC = "2026-08-01T00:00:00.000Z"

# One day is exactly 86,400 seconds wherever the PRD expresses a window in days (PRD §2.7).
SECONDS_PER_DAY = 86_400

# StateProgram documented defaults (PRD §3.1).
PROGRAM_DEFAULTS = {
    "posting_deadline_day": 10,
    "hold_window_days": 3,
    "correction_window_days": 15,
    "combo_cooldown_days": 7,
    "quantity_discount_allowed": True,
    "combination_sale_allowed": True,
    "max_quantity_discount_pct": 0.15,
    "max_promotional_allowance_pct": 0.05,
    "depletion_allowance_per_case_cents": 150,
    "late_filing_penalty_cents": 250_000,
    "repeat_correction_penalty_cents": 100_000,
    "frivolous_amendment_penalty_cents": 75_000,
    "off_posted_penalty_rate_pct": 0.40,
    "max_corrections_per_schedule": 2,
}

# Declared input ranges for StateProgram configuration fields (PRD §3.1).
PROGRAM_RANGES = {
    "posting_deadline_day_min": 1,
    "posting_deadline_day_max": 28,
    "hold_window_days_min": 1,
    "correction_window_days_min": 1,
    "combo_cooldown_days_min": 0,
}

# Clerical limit on an error correction's variance_pct (PRD §3.6).
CLERICAL_LIMIT_PCT = 0.10

# Combination sale discount bands keyed on the pre-discount floor (PRD §3.5).
COMBINATION_BANDS = {
    "low_floor_max_exclusive": 50_000,
    "mid_floor_max_exclusive": 150_000,
    "low_band_pct": 0.00,
    "mid_band_pct": 0.05,
    "high_band_pct": 0.10,
}

# Invoice handling surcharge bands keyed on subtotal_cents (PRD §3.8).
SURCHARGE_BANDS = {
    "low_subtotal_max_exclusive": 500_000,
    "mid_subtotal_max_exclusive": 2_000_000,
    "low_rate": 0.000,
    "mid_rate": 0.005,
    "high_rate": 0.010,
}

# Audit escalation tiers keyed on prior_violation_count (PRD §3.9).
AUDIT_TIERS = {
    "no_escalation_max": 2,
    "mid_escalation_min": 3,
    "mid_escalation_max": 9,
    "high_escalation_min": 10,
    "no_escalation_multiplier": 1.00,
    "mid_escalation_multiplier": 1.50,
    "high_escalation_multiplier": 2.00,
}

# Pagination envelope defaults and bounds (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
    "min_offset": 0,
}

# Values reused by the test suite so scenarios stay readable.
TEST_DEFAULTS = {
    "STATE_CODE": "TX",
    "PROGRAM_NAME": "Texas Price Posting Program",
    "LICENSE_NUMBER_A": "W-1001",
    "LICENSE_NUMBER_B": "W-2002",
    "LEGAL_NAME_A": "Lone Star Distributing",
    "LEGAL_NAME_B": "Gulf Coast Beverage",
    "BRAND_NAME": "Rio Reserve",
    "SUPPLIER_NAME": "Rio Supply Co",
    "BEVERAGE_CLASS": "SPIRITS",
    "REGISTRATION_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "REGISTRATION_EXPIRES_ON": "2027-12-31T23:59:59Z",
    "POSTING_MONTH": "2026-09",
    "SIZE_ML": 750,
    "BOTTLES_PER_CASE": 12,
    "CASE_PRICE_CENTS": 120_000,
    "UNIT_PRICE_CENTS": 11_000,
    "RETAILER_LICENSE_NUMBER": "R-5500",
    "FILING_AGENT_NAME": "Fay Filer",
    "CERTIFYING_OFFICER_NAME": "Cora Certifier",
}
