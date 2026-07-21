"""Domain thresholds — numeric constants drawn from the PRD's calculations (§3)."""

# Applicant underwriting (PRD §3.1)
CREDIT_FLOOR = 580
TIER_A_CREDIT = 720
TIER_A_DTI = 0.35
TIER_B_CREDIT = 660
TIER_B_DTI = 0.45
TIER_C_CREDIT = 600
TIER_C_DTI = 0.55

# Guarantee fee (PRD §3.2 / §3.4)
COVERED_FRACTION = 0.90
MAX_COVERAGE_MONTHS = 12
MIN_FEE_CENTS = 15000
MAX_FEE_CENTS = 500000
TIER_RATE = {"A": 0.05, "B": 0.08, "C": 0.12, "D": 0.18}
PROVISIONAL_TIER = "C"

# Affordability (PRD §3.4)
RENT_INCOME_MAX = 0.40

# Portfolio exposure (PRD §2.7 / §3.4 / §3.5)
TIER_WEIGHT = {"A": 0.5, "B": 0.8, "C": 1.2, "D": 2.0}
POSTURE_WARN_FRACTION = 0.80

# Agreement unit-coverage buffer (PRD §3.3)
UNIT_BUFFER_DAYS = 30

# Pagination defaults (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Server logical-clock startup default (PRD §2.10)
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"

# --- Canonical numbers reused across fixtures/tests for the "standard" guarantee ---
# rent 249999, coverage_months 6, term 12, applicant tier A (credit 740, dti 0.20).
STD_MONTHLY_RENT_CENTS = 249999
STD_COVERAGE_MONTHS = 6
STD_TERM_MONTHS = 12
STD_PER_MONTH_COVERAGE_CENTS = 224999          # round_half_up(249999 * 0.90)
STD_TOTAL_COVERAGE_CENTS = 1349994             # 224999 * 6
STD_PROVISIONAL_FEE_CENTS = 161999             # round(0.12 * 1349994 * 1.0)
STD_FINAL_FEE_CENTS_TIER_A = 67500             # round(0.05 * 1349994 * 1.0)
