"""Domain thresholds — numeric constants from the PRD's fee and verification logic.

NON_EXISTENT_UUID comes from the framework.
"""

# Required bond floor for the contractor verification bond leg (PRD §2.10).
REQUIRED_BOND_FLOOR = 15000

# Progressive base-permit-fee tier geometry (PRD §3.2).
TIER1_CEILING = 50000      # first $50,000 charged at the full base rate
TIER2_CEILING = 500000     # next band up to $500,000 at 80% of the base rate
TIER1_MULT = 1.00
TIER2_MULT = 0.80          # second tier multiplier
TIER3_MULT = 0.60          # above $500,000

# Jurisdiction defaults applied when omitted at creation (PRD §3.1).
DEFAULT_RENEWAL_FEE_PCT = 0.5
DEFAULT_PERMIT_VALID_DAYS = 180

# Shared jurisdiction fee schedule reused across most test setups, matching the
# values the design indices assume (rate 10, min 100, pr_pct 0.65, sqft 120).
STD_JURISDICTION = {
    "valuation_fee_rate_per_1000": 10,
    "square_foot_rate": 120,
    "plan_review_fee_pct": 0.65,
    "minimum_permit_fee": 100,
}

# Total fee for the cheapest standard permit (declared_valuation 2000 floored to
# base 100.00, surcharge 65.00) — the amount most fixtures pay to reach balance 0.
STD_SMALL_PERMIT_TOTAL_FEE = 165.00
