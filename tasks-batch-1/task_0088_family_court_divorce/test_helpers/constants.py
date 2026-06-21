"""Domain thresholds and canonical test values from the PRD calculations (Section 3).

The canonical CA guideline schedule mirrors the one used throughout the design
indices; tests reuse it so the pre-computed literal amounts hold.
"""

# Guideline schedule tuning-parameter defaults (PRD §3.1).
SCHEDULE_DEFAULTS = {
    "spousal_payor_pct": 0.40,
    "spousal_payee_offset_pct": 0.50,
    "shared_custody_threshold_pct": 0.40,
    "long_marriage_months": 120,
}

# Parenting-time fraction is carried to four decimals (PRD §2.8 / §3.4).
TOTAL_OVERNIGHTS = 365

# Pagination bounds (PRD §2.3).
PAGINATION = {"limit_default": 10, "limit_min": 1, "limit_max": 100, "offset_min": 0}

# Canonical CA full three-tier schedule used by divergence / mode-(a) tests.
CA_FULL_TIERS = [
    {"min_combined_monthly_cents": 0, "max_combined_monthly_cents": 999999,
     "base_cents_one_child": 100000, "marginal_pct_per_extra_child": 0.50},
    {"min_combined_monthly_cents": 1000000, "max_combined_monthly_cents": 1999999,
     "base_cents_one_child": 150000, "marginal_pct_per_extra_child": 0.50},
    {"min_combined_monthly_cents": 2000000, "max_combined_monthly_cents": 99999999,
     "base_cents_one_child": 200000, "marginal_pct_per_extra_child": 0.50},
]

# Single wide tier — used where tier selection is irrelevant to the test.
CA_WIDE_TIER = [
    {"min_combined_monthly_cents": 0, "max_combined_monthly_cents": 99999999,
     "base_cents_one_child": 100000, "marginal_pct_per_extra_child": 0.50},
]

# Default operator ids used by opaque officer roles.
DEFAULT_JUDGE_USER_ID = "u-judge"
DEFAULT_MEDIATOR_USER_ID = "u-med"

# Default filing fee used across fixtures.
DEFAULT_FILING_FEE_CENTS = 43500
