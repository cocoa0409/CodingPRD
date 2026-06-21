"""Domain thresholds — numeric constants from the PRD premium, risk, cash-value,
and loan calculations (PRD §2.6, §3.2, §3.4, §3.5, §3.7, §3.9)."""

# Premium engine multipliers (milli-units), PRD §3.2 / §3.5
PREMIUM = {
    "TOBACCO_MULT_MILLI": 1500,
    "NON_TOBACCO_MULT_MILLI": 1000,
    "PROVISIONAL_CLASS_MULT_MILLI": 1000,   # provisional assumes STANDARD
    "STANDARD_CLASS_MULT_MILLI": 1000,
    "PREFERRED_CLASS_MULT_MILLI": 850,
    "TABLE_STEP_MILLI": 250,                # each table step adds 250 milli over STANDARD
    "THOUSANDS_DIVISOR": 100000,            # face cents / 100000 = thousands
}

# Risk classification debit bands, PRD §3.4
RISK = {
    "BMI_BAND_1_MAX": 27.5,
    "BMI_BAND_2_MAX": 32.0,
    "BMI_BAND_3_MAX": 37.0,
    "BMI_BAND_DEBITS": [0, 50, 100, 200],
    "BP_BAND_1_MAX": 135,
    "BP_BAND_2_MAX": 150,
    "BP_BAND_DEBITS": [0, 50, 100],
    "TOBACCO_DEBITS": 50,
    "MIB_FLAGGED_DEBITS": 75,
    "PREFERRED_MAX_DEBITS": 50,     # total < 50 -> PREFERRED
    "STANDARD_MAX_DEBITS": 100,     # 50 <= total < 100 -> STANDARD
    "TABLE_STEP_DEBITS": 50,
    "TABLE_CAP": 8,
}

# Cash-value accrual, PRD §3.7
CASH_VALUE = {
    "BPS_DENOMINATOR": 10000,
}

# Loan eligibility, PRD §3.9
LOAN = {
    "PCT_DENOMINATOR": 100,
}

# Product defaults applied when omitted on creation, PRD §3.1
PRODUCT_DEFAULTS = {
    "contestability_months": 24,
    "grace_period_days": 31,
    "max_loan_to_cash_value_pct": 90,
    "exam_validity_days": 180,
}

# Reusable test values shared across the standard scenario
TEST_DEFAULTS = {
    "BASE_RATE_PER_THOUSAND_CENTS": 250,
    "MAX_FACE_AMOUNT_CENTS": 100_000_000,
    "CASH_VALUE_ACCRUAL_RATE_BPS": 300,
    "FACE_AMOUNT_CENTS": 50_000_000,
    "STANDARD_PREMIUM_CENTS": 125000,     # face 50000000, non-tobacco, STANDARD
    "GROSS_AFTER_ISSUE_CENTS": 3750,      # round_half_up(125000 * 300 / 10000)
    "GROSS_AFTER_TWO_PREMIUMS_CENTS": 11250,  # 3750 + round_half_up(250000*300/10000)
}
