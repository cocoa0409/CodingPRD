"""Domain thresholds and fixture economics (PRD §2.4, §3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Deadline / window constants (PRD §3).
THRESHOLDS = {
    "ACK_SLA_DAYS": 5,
    "EVAL_SLA_DAYS": 30,
    "TRIAL_PERIODS": 3,
    "TRIAL_INTERVAL_DAYS": 30,
    "OFFER_VALIDITY_DAYS": 30,
    "RESCISSION_WINDOW_DAYS": 3,
    "APPEAL_WINDOW_DAYS": 14,
    "APPEAL_ELIGIBILITY_MIN_DAYS": 90,
    "SALE_BLOCK_MIN_DAYS": 37,
    "REFERRAL_MIN_DELINQUENCY_DAYS": 120,
    "MIN_SALE_NOTICE_DAYS": 14,
    "SURPLUS_REFUND_MIN_CENTS": 5000,
    "CUSHION_MONTHS": 2,
}

# Canonical STD_MOD waterfall program used by most scenarios (PRD §3.5).
STD_MOD_DEFAULTS = {
    "code": "STD_MOD",
    "waterfall_rank": 1,
    "target_dti_bp": 3100,
    "rate_floor_bp": 200,
    "rate_step_bp": 25,
    "max_term_months": 480,
    "max_forbearance_pct_bp": 3000,
    "min_delinquency_days": 61,
    "max_delinquency_days": 720,
}

# Fixture A loan economics: a moderately delinquent loan whose waterfall
# offer is reached by rate reduction alone.
FIXTURE_A_LOAN = {
    "property_state_code": "CA",
    "unpaid_principal_balance_cents": 20_000_000,
    "interest_rate_bp": 600,
    "remaining_term_months": 240,
    "arrears_cents": 1_200_000,
    "escrow_balance_cents": 30_000,
    "escrow_monthly_cents": 30_000,
    "delinquency_days": 150,
}
FIXTURE_A_STATED_INCOME = 480_000
# biweekly 200000 * 26/12 = 433333 (rounded half-up); tax 600000/12 = 50000.
FIXTURE_A_DOCS = [
    ("PAYSTUB", {
        "gross_per_period_cents": 200_000,
        "pay_frequency": "BIWEEKLY",
        "pay_period_end_date": "2026-07-31",
    }),
    ("TAX_RETURN", {"annual_gross_cents": 600_000}),
    ("HARDSHIP_AFFIDAVIT", {}),
    ("BANK_STATEMENT", {}),
]
FIXTURE_A_VERIFIED_INCOME = 483_333
FIXTURE_A_TRIAL_PAYMENT_CENTS = 178_842  # offered pi 148842 + escrow 30000

# Fixture B loan economics: forbearance solves the payment exactly to target.
FIXTURE_B_LOAN = {
    "property_state_code": "TX",
    "unpaid_principal_balance_cents": 30_000_000,
    "interest_rate_bp": 600,
    "remaining_term_months": 240,
    "arrears_cents": 6_000_000,
    "escrow_balance_cents": 0,
    "escrow_monthly_cents": 0,
    "delinquency_days": 150,
}
FIXTURE_B_STATED_INCOME = 322_581
FIXTURE_B_DOCS = [
    ("PAYSTUB", {
        "gross_per_period_cents": 322_581,
        "pay_frequency": "MONTHLY",
        "pay_period_end_date": "2026-07-31",
    }),
    ("HARDSHIP_AFFIDAVIT", {}),
    ("BANK_STATEMENT", {}),
]
FIXTURE_B_VERIFIED_INCOME = 322_581
FIXTURE_B_TRIAL_PAYMENT_CENTS = 100_000

# Fixture C economics: fixture B loan terms but low verified income -> DENIAL.
FIXTURE_C_STATED_INCOME = 100_000
FIXTURE_C_DOCS = [
    ("PAYSTUB", {
        "gross_per_period_cents": 100_000,
        "pay_frequency": "MONTHLY",
        "pay_period_end_date": "2026-07-31",
    }),
    ("HARDSHIP_AFFIDAVIT", {}),
    ("BANK_STATEMENT", {}),
]
FIXTURE_C_VERIFIED_INCOME = 100_000
