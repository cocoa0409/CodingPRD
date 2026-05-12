"""Domain thresholds — numeric constants from PRD prose.

All literals correspond to numeric thresholds, defaults, or magic constants
named in PRD §2 / §3. The reference implementation is expected to use these
same values verbatim.
"""

# Pagination — PRD §2.3
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Allocation calculation — PRD §3.2
# "the historical baseline multiplied by an annual-reduction factor of 0.97"
ANNUAL_REDUCTION_FACTOR = 0.97

# Cycle ratios — PRD §3.1
# "The free-paid ratio must lie between 0.0 and 1.0 inclusive"
FREE_PAID_RATIO_MIN = 0.0
FREE_PAID_RATIO_MAX = 1.0
# "the CCER cap must lie between 0.0 and 0.20 inclusive"
CCER_CAP_PCT_MIN = 0.0
CCER_CAP_PCT_MAX = 0.20

# Borrow cap — PRD §3.6
# "declared borrow amount must be at most the verified emissions multiplied by 0.05"
BORROW_CAP_PCT = 0.05

# Penalty severity breakpoints — PRD §3.6
# "if deficit_pct is strictly less than 0.05, severity is MINOR;
#  otherwise if deficit_pct is strictly less than 0.20, severity is MODERATE"
SEVERITY_MINOR_BREAKPOINT = 0.05
SEVERITY_MODERATE_BREAKPOINT = 0.20

# Penalty rates by jurisdiction × severity — PRD §3.6
JURISDICTION_PENALTY_RATE = {
    "JD_ALPHA": {"MINOR": 100.00, "MODERATE": 200.00, "SEVERE": 500.00},
    "JD_BETA":  {"MINOR": 80.00,  "MODERATE": 180.00, "SEVERE": 450.00},
    "JD_GAMMA": {"MINOR": 120.00, "MODERATE": 250.00, "SEVERE": 600.00},
}

# Mandatory deduction multiplier — PRD §3.6
# "The mandatory_deduction_amount is the deficit_amount multiplied by 1.5"
MANDATORY_DEDUCTION_MULTIPLIER = 1.5

# Penalty due — PRD §3.6
# "payment_due_at is set to 30 days after issuance"
PAYMENT_DUE_DAYS = 30

# Verification visit buffer — PRD §3.4
# "the visit must be at least 7 days in the future from the time of assignment"
VERIFICATION_VISIT_MIN_DAYS = 7

# Dispute window — PRD §3.4
# "only within 14 days of the assignment's report_issued_at"
DISPUTE_WINDOW_DAYS = 14

# Emission report submission deadline offset — PRD §3.3
# "submission_deadline as the cycle's compliance deadline minus 90 days"
SUBMISSION_DEADLINE_OFFSET_DAYS = 90

# Trade fees — PRD §3.5
TRADE_FEE_BASE_RATE_BY_CHANNEL = {
    "EXCHANGE": 0.0010,
    "BLOCK":    0.0006,
    "OTC":      0.0008,
}
# "tier 1 covers gross values from zero up to and including 100,000"
TIER1_CAP = 100_000
# "tier 2 covers the portion strictly above 100,000 up to and including 1,000,000"
TIER2_CAP = 1_000_000
# "80% of the base rate applies on this portion only" / "60% of the base rate"
TIER2_DISCOUNT = 0.80
TIER3_DISCOUNT = 0.60

# Settlement — PRD §3.7
# "carry-forward cap equals the next-cycle allocation multiplied by 0.10"
CARRY_FORWARD_CAP_PCT = 0.10
# "repurchased by the regulator at a floor price of 30.00 currency units"
REPURCHASE_FLOOR_PRICE = 30.00


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "ANNUAL_REDUCTION_FACTOR",
    "FREE_PAID_RATIO_MIN",
    "FREE_PAID_RATIO_MAX",
    "CCER_CAP_PCT_MIN",
    "CCER_CAP_PCT_MAX",
    "BORROW_CAP_PCT",
    "SEVERITY_MINOR_BREAKPOINT",
    "SEVERITY_MODERATE_BREAKPOINT",
    "JURISDICTION_PENALTY_RATE",
    "MANDATORY_DEDUCTION_MULTIPLIER",
    "PAYMENT_DUE_DAYS",
    "VERIFICATION_VISIT_MIN_DAYS",
    "DISPUTE_WINDOW_DAYS",
    "SUBMISSION_DEADLINE_OFFSET_DAYS",
    "TRADE_FEE_BASE_RATE_BY_CHANNEL",
    "TIER1_CAP",
    "TIER2_CAP",
    "TIER2_DISCOUNT",
    "TIER3_DISCOUNT",
    "CARRY_FORWARD_CAP_PCT",
    "REPURCHASE_FLOOR_PRICE",
]
