"""Domain thresholds and calculation constants (PRD sections 3.1-3.8)."""

# Underwriting rate and DSCR policy floors (PRD section 3.2)
POLICY_RATE_BPS = 700
ADDBACK_CAP_RATIO = 0.25
STRESS_REVENUE_HAIRCUT = 0.15
DSCR_MIN = 1.25
STRESS_DSCR_MIN = 1.0

# Single-borrower cap (PRD section 3.1): $50,000,000.00 in cents
SINGLE_BORROWER_CAP_CENTS = 5_000_000_000

# Maximum loan-to-value by product type (PRD section 3.5)
MAX_LTV = {
    "CRE_TERM": 0.80,
    "CRE_CONSTRUCTION": 0.75,
    "CI_WORKING_CAPITAL": 0.60,
    "EQUIPMENT": 0.85,
    "AGRICULTURE": 0.75,
}

# Collateral valuation (PRD section 3.4)
ADVANCE_RATE = {
    "REAL_ESTATE": 0.75,
    "EQUIPMENT": 0.80,
    "RECEIVABLES": 0.50,
    "INVENTORY": 0.50,
    "AGRICULTURAL": 0.70,
}
LIQUIDATION_HAIRCUT = 0.85

# Origination fee tiers (PRD section 3.6)
FEE_TIER1_CAP_CENTS = 100_000_000
FEE_TIER2_CAP_CENTS = 400_000_000
FEE_TIER1_RATE = 0.0100
FEE_TIER2_RATE = 0.0075
FEE_TIER3_RATE = 0.0050

# Committee tiers (PRD section 3.5)
TIER_SMALL_CAP_CENTS = 100_000_000
TIER_STANDARD_CAP_CENTS = 1_000_000_000
COMMITTEE_SIZE = {"SMALL": 2, "STANDARD": 3, "LARGE": 5}
COMMITTEE_VOTES_REQUIRED = {"SMALL": 2, "STANDARD": 2, "LARGE": 4}
COMMITTEE_DECLINE_THRESHOLD = {"SMALL": 1, "STANDARD": 2, "LARGE": 2}

# Risk rating factor weights (PRD sections 3.2 / 3.5)
W_DSCR = 0.40
W_LEVERAGE = 0.30
W_COVERAGE = 0.20
W_TENURE = 0.10

# Waiver rationale minimum length (PRD sections 3.3 / 3.7)
WAIVER_RATIONALE_MIN_LEN = 20

# Logical clock startup default (PRD section 2.6)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Reusable waiver rationale texts (>= 20 characters)
RATIONALE_STRESS = "Stress shortfall accepted by credit policy desk"
RATIONALE_REG_O = "Insider relationship documented per Reg O file"
RATIONALE_DSCR = "Sized-down facility mitigates coverage shortfall"
RATIONALE_LTV = "Sized-down facility restores policy LTV compliance"
RATIONALE_COVERAGE = "Coverage shortfall accepted on sized-down commitment"
RATIONALE_ITEM = "Duplicate coverage verified on master policy"
RATIONALE_BREACH = "Borrower injected cure capital post-period"
