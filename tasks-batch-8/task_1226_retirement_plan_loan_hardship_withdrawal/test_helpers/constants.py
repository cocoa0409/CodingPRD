"""Domain thresholds and numeric constants used across PRD §3 calculations."""

# Statutory / calculation constants
VESTED_RATIO_NUM = 1
VESTED_RATIO_DEN = 2  # max loan = half of vested balance, floored to whole cents
IRC_CAP_CENTS = 5_000_000  # 50,000-dollar statutory ceiling
LOOKBACK_MONTHS = 12  # trailing lookback window for the high-water mark
REFI_FEE_CENTS = 10_000  # flat refinance fee ($100)

# Hardship gross-up fee tiers
FEE_TIER_THRESHOLD_CENTS = 1_000_000  # provisional-gross boundary ($10,000)
FEE_LOW_CENTS = 5_000
FEE_HIGH_CENTS = 7_500

# Document retention
DOCUMENT_RETENTION_YEARS = 7

# Loan eligibility lock after a deemed or offset distribution
ELIGIBILITY_LOCK_MONTHS = 12

# Logical clock startup default (PRD §2.6)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Default plan policy (PRD §3.1)
DEFAULT_PLAN_POLICY = {
    "max_loans_outstanding": 1,
    "min_loan_amount_cents": 100_000,
    "max_loan_amount_cents": 5_000_000,
    "max_term_months": 60,
    "interest_rate_bps": 500,
    "day_count_convention": "THIRTY_360",
    "allows_refinance": False,
    "refinance_min_months_since_disbursement": 12,
    "hardship_suspension_months": 6,
    "substantiation_standard": "FULL_DOCUMENTATION",
    "withholding_rate_bps": 2000,
    "allowed_hardship_reasons": [
        "MEDICAL", "FUNERAL", "EVICTION", "TUITION", "HOME_PURCHASE", "DISASTER",
    ],
    "loan_approval_chain": ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"],
    "hardship_approval_chain": ["PLAN_SPONSOR", "RECORDKEEPER_ADMIN"],
}

# Canonical 1,000,000c / 500bps / 12mo THIRTY_360 schedule (PRD §3.5 worked shape).
CANONICAL_LOAN = {
    "principal_amount_cents": 1_000_000,
    "term_months": 12,
    "scheduled_payment_cents": 85_607,
    # installment 1..5 interest portions under 30/360 at 500bps
    "installment_1_interest": 4_167,
    "installment_2_interest": 3_827,
    "installment_3_interest": 3_487,
    "installment_4_interest": 3_144,
    "installment_5_interest": 2_801,
    # after installment 1 is fully covered: 1,000,000 - (85,607 - 4,167) = 918,560
    "outstanding_after_first_payment": 918_560,
    # final installment absorbs the rounding remainder
    "final_installment_amount": 85_612,
    "final_installment_principal": 85_257,
    "final_installment_interest": 355,
    # full payoff total (sum of all 12 scheduled amounts)
    "full_payoff_cents": 1_027_289,
    # ACT/360 installment 1 interest for 2026-05-01 -> 2026-06-01 (31 actual days)
    "act_360_installment_1_interest": 4_306,
}

THRESHOLDS = {
    "IRC_CAP_CENTS": IRC_CAP_CENTS,
    "FEE_TIER_THRESHOLD_CENTS": FEE_TIER_THRESHOLD_CENTS,
    "FEE_LOW_CENTS": FEE_LOW_CENTS,
    "FEE_HIGH_CENTS": FEE_HIGH_CENTS,
    "REFI_FEE_CENTS": REFI_FEE_CENTS,
    "LOOKBACK_MONTHS": LOOKBACK_MONTHS,
    "ELIGIBILITY_LOCK_MONTHS": ELIGIBILITY_LOCK_MONTHS,
    "DOCUMENT_RETENTION_YEARS": DOCUMENT_RETENTION_YEARS,
}
