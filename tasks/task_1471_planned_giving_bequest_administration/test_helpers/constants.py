"""Domain thresholds — numeric constants named in the PRD.

Includes derived expected values for the standard test economics, computed per
the PRD actuarial formulas (annuity-immediate factor at the pinned discount
rate, term = 100 - age floored at 1, round half up to integer cents).
"""

# PRD actuarial / regulatory constants
MORTALITY_TERMINAL_AGE = 100
EXHAUSTION_LIMIT_BPS = 8500
RESERVE_DISCOUNT_RATE_BPS = 600
RESERVE_MULTIPLIER_BPS = 11000
COVERAGE_SOLVENT_BPS = 10000
LEGACY_THRESHOLD_CENTS = 10000000
DEFAULT_MIN_ENDOWMENT_CENTS = 2500000
PAYOUT_RATE_MIN_BPS = 500
PAYOUT_RATE_MAX_BPS = 5000

FREQUENCY_DIVISOR = {
    "ANNUAL": 1,
    "SEMIANNUAL": 2,
    "QUARTERLY": 4,
    "MONTHLY": 12,
}

# Logical clock startup value (PRD: "the logical clock reads exactly
# 2026-08-01T00:00:00Z" at server startup).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Reserve fund singleton defaults
RESERVE_FUND_NAME = "CGA_RESERVE"

# Standard test economics (gift 10_000_000, payout 600bps, QUARTERLY, age 80,
# funding month 2026-08 under a 500bps table):
#   annual annuity = round_half_up(10000000 * 600 / 10000) = 600000
#   quarterly payment = 600000 / 4 = 150000
#   payment count = 4 * (100 - 80) = 80
#   CGA reserve requirement = round_half_up(600000 * a(20)@6% * 1.1) = 7570148
STD_GIFT_CENTS = 10000000
STD_PAYOUT_BPS = 600
STD_AGE = 80
STD_FUNDING_MONTH = "2026-08"
STD_ANNUAL_ANNUITY_CENTS = 600000
STD_QUARTERLY_PAYMENT_CENTS = 150000
STD_QUARTERLY_PAYMENT_COUNT = 80
STD_CGA_RESERVE_REQUIREMENT_CENTS = 7570148

# Age-98 monthly CRT_ANNUITY economics (gift 1_665_017, 600bps):
#   annual annuity = 99901; monthly payment = round_half_up(99901/12) = 8325
#   payment count = 12 * (100 - 98) = 24; total scheduled = 24 * 8325 = 199800
#   booked deduction at 5% (n=2) = 1665017 - 185757 = 1479260
AGE98_GIFT_CENTS = 1665017
AGE98_ANNUAL_ANNUITY_CENTS = 99901
AGE98_MONTHLY_PAYMENT_CENTS = 8325
AGE98_PAYMENT_COUNT = 24
AGE98_TOTAL_SCHEDULED_CENTS = 199800
AGE98_BOOKED_DEDUCTION_CENTS = 1479260

# Age-80 500bps QUARTERLY CRT_ANNUITY on 10_000_000 at a 500bps table:
#   annual 500000; quarterly 125000; liability a(20)@5% = 6231105;
#   deduction/remainder = 10000000 - 6231105 = 3768895
CRAT80_ANNUAL_ANNUITY_CENTS = 500000
CRAT80_QUARTERLY_PAYMENT_CENTS = 125000
CRAT80_ACTUARIAL_LIABILITY_CENTS = 6231105
CRAT80_DEDUCTION_CENTS = 3768895

# Revaluation at valuation_date 2027-08-01 (one whole year after 2026-08):
# ages advance to 81, n = 19, a(19)@5% = 12.0853208...
#   CRT_ANNUITY (fixed annual 600000): liability 7251193, remainder 2748807
#   CRT_UNITRUST after corpus update to 12_000_000: annual 720000,
#     liability 8701431, remainder 3298569, quarterly payment 180000
REVAL_CRAT_LIABILITY_CENTS = 7251193
REVAL_CRAT_REMAINDER_CENTS = 2748807
REVAL_CRUT_CORPUS_CENTS = 12000000
REVAL_CRUT_ANNUAL_ANNUITY_CENTS = 720000
REVAL_CRUT_PAYMENT_CENTS = 180000
REVAL_CRUT_TOTAL_SCHEDULED_CENTS = 14400000
REVAL_CRUT_LIABILITY_CENTS = 8701431
REVAL_CRUT_REMAINDER_CENTS = 3298569
REVAL_TOTAL_LIABILITY_CENTS = 15952624
REVAL_TOTAL_REMAINDER_CENTS = 6047376

# Illustration deduction figures (500bps table):
#   single life age 70, 600bps on 10_000_000: annual 600000, deduction 776529
#   joint lives 75/70, 500bps on 10_000_000: annual 500000, deduction 2313774
#   single life age 105 (term floored to 1), 600bps: deduction 9428571
ILL_AGE70_DEDUCTION_CENTS = 776529
ILL_JOINT_75_70_DEDUCTION_CENTS = 2313774
ILL_AGE105_DEDUCTION_CENTS = 9428571

# Same single-life age-70 economics under a 600bps table: deduction 1741101
BOOKED_AGE70_RATE600_DEDUCTION_CENTS = 1741101

# Exhaustion-band economics: CRT_ANNUITY age 80, 700bps ANNUAL on 10_000_000:
# pv = 8723547 (passes the 10% remainder test: deduction 1276453),
# exceeds the 85% exhaustion limit of 8500000.
EXHAUSTION_BAND_PAYOUT_BPS = 700
