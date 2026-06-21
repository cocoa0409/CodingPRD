"""Domain thresholds — numeric constants from the Auto Title Loan PRD calculations.

The generic NON_EXISTENT_UUID comes from the framework.
"""

# Condition haircut basis points applied to the raw valuation on finalize.
CONDITION_HAIRCUT_BPS = {
    "EXCELLENT": 0,
    "GOOD": 500,
    "FAIR": 1500,
    "POOR": 3000,
}

# Late fee assessment constants.
LATE_FEE_BPS = 500
LATE_FEE_FLOOR_CENTS = 1500
LATE_FEE_CAP_CENTS = 5000

# Flat repossession recovery fee added to redemption / reinstatement (in DEFAULT) / deficiency.
REPO_RECOVERY_FEE_CENTS = 25000

# Fixed sale cost subtracted from gross sale proceeds when computing deficiency.
SALE_COST_CENTS = 30000

# Amortization schedule date spacing.
FIRST_DUE_OFFSET_DAYS = 30
DUE_SPACING_DAYS = 30

# Basis-points denominator: 10000 bps == 100%.
BPS_DENOMINATOR = 10000


# Canonical CA profile parameters used throughout the design indices.
CA_PROFILE = {
    "state_code": "CA",
    "max_apr_bps": 3600,
    "max_ltv_bps": 5000,
    "max_renewals": 2,
    "min_term_months": 3,
    "max_term_months": 24,
    "redemption_grace_days": 10,
    "valuation_basis": "AUCTION",
}

# Canonical VA profile (TRADE_IN basis) used for the trade-in-vs-auction divergence test.
VA_PROFILE = {
    "state_code": "VA",
    "max_apr_bps": 3600,
    "max_ltv_bps": 5000,
    "max_renewals": 2,
    "min_term_months": 3,
    "max_term_months": 24,
    "redemption_grace_days": 10,
    "valuation_basis": "TRADE_IN",
}

# Canonical appraisal valuation inputs used across the design indices.
DEFAULT_TRADE_IN_VALUE_CENTS = 2000000
DEFAULT_AUCTION_VALUE_CENTS = 1600000
DEFAULT_CONDITION_GRADE = "GOOD"

# Canonical loan parameters reused throughout the design indices.
DEFAULT_PRINCIPAL_CENTS = 600000
DEFAULT_CONTRACT_APR_BPS = 3600
DEFAULT_TERM_MONTHS = 3

# Pre-computed canonical figures (copied verbatim from the design indices).
# Appraisal under AUCTION/GOOD: basis 1600000*0.95 = 1520000; LTV 50% -> 760000.
AUCTION_BASIS_VALUE_CENTS = 1520000
AUCTION_MAX_PRINCIPAL_CENTS = 760000
# Appraisal under TRADE_IN/GOOD: basis 2000000*0.95 = 1900000; LTV 50% -> 950000.
TRADE_IN_BASIS_VALUE_CENTS = 1900000
TRADE_IN_MAX_PRINCIPAL_CENTS = 950000

# Reinstatement / redemption amounts on the canonical 600000-principal CA loan with
# seq1+seq2 PAST_DUE at clock 2026-03-15 (no repo order).
CANONICAL_REINSTATEMENT_AMOUNT_CENTS = 434236
CANONICAL_REDEMPTION_AMOUNT_CENTS = 640176
