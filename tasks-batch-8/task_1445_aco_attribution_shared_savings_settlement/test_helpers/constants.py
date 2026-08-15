"""Domain thresholds and calculation constants (PRD §2.8, §3.2–§3.8)."""

THRESHOLDS = {
    # PRD §3.2: high-cost claimant watch fires at >= 10000000 cents YTD.
    "HIGH_COST_THRESHOLD_CENTS": 10000000,
    # PRD §3.6: per-beneficiary truncation cap.
    "TRUNCATION_CAP_CENTS": 20000000,
    # PRD §3.5: quality multiplier tiers.
    "QUALITY_FULL_THRESHOLD": 0.7000,
    "QUALITY_PARTIAL_THRESHOLD": 0.5000,
    # PRD §3.8: settlement appeal window in days from finalized_at.
    "APPEAL_WINDOW_DAYS": 30,
    # PRD §3.8: rebuttal round cap.
    "APPEAL_ROUND_CAP": 2,
}

RATES = {
    # PRD §3.5: sharing base rate by track.
    "BASE_RATE_ONE_SIDED": 0.40,
    "BASE_RATE_TWO_SIDED": 0.60,
    # PRD §3.6: MSR / MLRR / caps / sequestration.
    "MSR_RATE": 0.02,
    "MLRR_RATE": 0.02,
    "SAVINGS_CAP_RATE": 0.10,
    "LOSS_CAP_RATE": 0.05,
    "LOSS_SHARE_RATE_TWO_SIDED": 0.40,
    "SEQUESTRATION_RATE": 0.02,
}

BENCHMARK = {
    # PRD §3.4: per-member-per-month base and annualization.
    "PMPM_BASE_CENTS": 100000,
    "MONTHS_PER_YEAR": 12,
    "UPDATE_FACTOR_PROVISIONAL": 1.030,
    "UPDATE_FACTOR_FINAL": 1.021,
    # PRD §3.4: risk score components.
    "RISK_BASE": 1.00,
    "RISK_DUAL": 0.25,
    "RISK_ESRD": 0.40,
    "RISK_DISABLED": 0.15,
    "RISK_AGED_75_PLUS": 0.05,
    "RISK_AGED_THRESHOLD": 75,
}

# PRD §2.8: logical clock startup default.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Canonical 2026 performance-year span used across fixtures.
PERFORMANCE_START = "2026-01-01"
PERFORMANCE_END = "2026-12-31"

# Canonical retrospective attribution window: [start, end) covering the year.
RETRO_WINDOW_START = "2026-01-01"
RETRO_WINDOW_END = "2027-01-01"
