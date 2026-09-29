"""Domain constants for the Insurance Premium Finance API.

Every value here is stated verbatim in the PRD; nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD: "The clock starts at exactly 2026-08-01T00:00:00Z")
# ---------------------------------------------------------------------------
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Money / rate conventions
# ---------------------------------------------------------------------------
BPS_DENOMINATOR = 10000
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Volume-tier rate schedule keyed on amount_financed_cents
# ---------------------------------------------------------------------------
TIER1_MAX_AMOUNT_FINANCED_CENTS = 500000
TIER1_RATE_BPS = 1800
TIER2_MAX_AMOUNT_FINANCED_CENTS = 2000000
TIER2_RATE_BPS = 1500
TIER3_RATE_BPS = 1200

# ---------------------------------------------------------------------------
# Deficiency cancellation-fee tiers keyed on the PRE-FEE residual
# ---------------------------------------------------------------------------
DEFICIENCY_FEE_TIER1_MAX_CENTS = 25000
DEFICIENCY_FEE_TIER1_CENTS = 2500
DEFICIENCY_FEE_TIER2_CENTS = 5000

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------
PREMIUM_VARIANCE_TOLERANCE_BPS = 2500
MAX_OVERPAYMENT_CENTS = 50000

# ---------------------------------------------------------------------------
# First-installment due-date window
# ---------------------------------------------------------------------------
FIRST_DUE_DATE_MAX_DAYS_AHEAD = 60

# ---------------------------------------------------------------------------
# Pagination envelope (PRD list-endpoint contract)
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------------
# Canonical TX statutory regime used throughout the suite.
# ADD_ON, RULE_OF_78 rebates, PRO_RATA unearned premium.
# ---------------------------------------------------------------------------
TX_RULE = {
    "state_code": "TX",
    "finance_charge_method": "ADD_ON",
    "max_annual_rate_bps": 1800,
    "max_service_fee_cents": 2000,
    "min_down_payment_bps": 1500,
    "max_term_months": 10,
    "late_fee_bps": 500,
    "late_fee_min_cents": 500,
    "late_fee_max_cents": 10000,
    "grace_period_days": 10,
    "noic_notice_days": 10,
    "unearned_premium_method": "PRO_RATA",
    "short_rate_penalty_bps": 1000,
    "rebate_method": "RULE_OF_78",
    "max_late_fees_per_agreement": 3,
    "license_required": True,
}

# ---------------------------------------------------------------------------
# Canonical CA statutory regime.
# SIMPLE_INTEREST, ACTUARIAL rebates, SHORT_RATE unearned premium.
# ---------------------------------------------------------------------------
CA_RULE = {
    "state_code": "CA",
    "finance_charge_method": "SIMPLE_INTEREST",
    "max_annual_rate_bps": 1200,
    "max_service_fee_cents": 1500,
    "min_down_payment_bps": 2000,
    "max_term_months": 8,
    "late_fee_bps": 1000,
    "late_fee_min_cents": 1000,
    "late_fee_max_cents": 1500,
    "grace_period_days": 7,
    "noic_notice_days": 15,
    "unearned_premium_method": "SHORT_RATE",
    "short_rate_penalty_bps": 1000,
    "rebate_method": "ACTUARIAL",
    "max_late_fees_per_agreement": 2,
    "license_required": True,
}

# ---------------------------------------------------------------------------
# The canonical "600k note" pricing, used as a precondition by many recipes:
#   amount_financed = 600000 - 100000 + 2000 = 502000  (tier 2 -> 1500 bps)
#   finance_charge   = round_half_up(502000 * 1500 * 6 / (10000 * 12)) = 37650
#   total_of_payments = 539650
#   installments      = 89941 x 5 then 89945, fc component 6275 each
# ---------------------------------------------------------------------------
NOTE_600K_AMOUNT_FINANCED_CENTS = 502000
NOTE_600K_FINANCE_CHARGE_CENTS = 37650
NOTE_600K_TOTAL_OF_PAYMENTS_CENTS = 539650
NOTE_600K_INSTALLMENT_CENTS = 89941
NOTE_600K_LAST_INSTALLMENT_CENTS = 89945
NOTE_600K_FC_COMPONENT_CENTS = 6275
NOTE_600K_PRINCIPAL_COMPONENT_CENTS = 83666
NOTE_600K_LATE_FEE_CENTS = 4497

# ---------------------------------------------------------------------------
# The FIXTURE-TX9 note: 1250000 attested premium, down 300000, service fee
# 2000, nine installments.  amount_financed 1252000, finance charge 140850,
# total_of_payments 1392850, installments 154761 x 8 then 154762.
# ---------------------------------------------------------------------------
TX9_AMOUNT_FINANCED_CENTS = 1252000
TX9_FINANCE_CHARGE_CENTS = 140850
TX9_TOTAL_OF_PAYMENTS_CENTS = 1392850
TX9_INSTALLMENT_CENTS = 154761
TX9_LAST_INSTALLMENT_CENTS = 154762
TX9_FC_COMPONENT_CENTS = 15650
TX9_PRINCIPAL_COMPONENT_CENTS = 139111
TX9_LATE_FEE_CENTS = 7738
