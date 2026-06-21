"""Domain thresholds — numeric constants from the PRD computations (integer cents)."""

# Standard deduction by filing status (PRD §3.5)
STANDARD_DEDUCTION = {
    "SINGLE": 1_500_000,
    "MARRIED_JOINT": 3_000_000,
    "MARRIED_SEPARATE": 1_500_000,
    "HEAD_OF_HOUSEHOLD": 2_250_000,
}

# Marginal bracket thresholds (PRD §3.5), in cents.
# SINGLE / MARRIED_SEPARATE / HEAD_OF_HOUSEHOLD share the SINGLE tiers.
BRACKET_SINGLE_TIER1 = 1_160_000   # 10% up to here
BRACKET_SINGLE_TIER2 = 4_715_000   # 12% up to here, 22% above
BRACKET_MJ_TIER1 = 2_320_000       # 10% up to here
BRACKET_MJ_TIER2 = 9_430_000       # 12% up to here, 22% above

# Credit constants (PRD §3.5)
CTC_PER_CHILD = 200_000            # $2,000.00 per qualifying child (age < 17)
AOTC_PER_STUDENT = 250_000         # $2,500.00 per student dependent
AOTC_PHASEOUT_START = 8_000_000    # AGI <= start -> full AOTC
AOTC_PHASEOUT_END = 9_000_000      # AGI >= end -> AOTC zero
AOTC_REFUNDABLE_PCT = 40           # 40% of allowed is refundable
EITC_PHASEOUT_START = 2_000_000    # AGI excess phases out EITC
EITC_PHASEOUT_RATE_PCT = 21        # 21% of AGI excess
EITC_MAX_BY_CHILDREN = {0: 60_000, 1: 396_000, 2: 655_000}

# Capital loss (PRD §3.5)
CAPITAL_LOSS_LIMIT = 300_000       # net loss floored at -$3,000.00

# Underpayment penalty / safe harbors (PRD §3.7)
HIGH_INCOME_AGI = 15_000_000       # prior AGI > this -> 110% prior-year harbor
PENALTY_RATE_PCT = 8               # 8% of shortfall
CURRENT_YEAR_HARBOR_PCT = 90       # 90% of current-year tax_after_credits
QUARTER_DUE_DATES = {
    "Q1": "2025-04-15T23:59:59Z",
    "Q2": "2025-06-16T23:59:59Z",
    "Q3": "2025-09-15T23:59:59Z",
    "Q4": "2026-01-15T23:59:59Z",
}

TAX_YEAR = 2025
