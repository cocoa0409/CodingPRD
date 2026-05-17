"""Domain thresholds — numeric constants traceable to PRD.md sentences.

Every constant traces back to a verbatim sentence in PRD.md. The doc
strings beside each constant carry the exact PRD wording so tests can
verify their boundary picks are not invented numbers.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Pay periods per year — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the per-paycheck federal withholding uses an annualized
# projection. The system first multiplies the paycheck's gross by 26
# (the number of biweekly pay periods per year)".
PAY_PERIODS_PER_YEAR: int = 26

# ---------------------------------------------------------------------------
# Standard deductions — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the standard deduction corresponding to the filing status —
# 1,390,000 cents for SINGLE, 2,780,000 cents for MARRIED_JOINT, and
# 2,090,000 cents for HEAD_OF_HOUSEHOLD".
STANDARD_DEDUCTION_SINGLE_CENTS: int = 1_390_000
STANDARD_DEDUCTION_MARRIED_JOINT_CENTS: int = 2_780_000
STANDARD_DEDUCTION_HEAD_OF_HOUSEHOLD_CENTS: int = 2_090_000

STANDARD_DEDUCTION: dict = {
    "SINGLE": STANDARD_DEDUCTION_SINGLE_CENTS,
    "MARRIED_JOINT": STANDARD_DEDUCTION_MARRIED_JOINT_CENTS,
    "HEAD_OF_HOUSEHOLD": STANDARD_DEDUCTION_HEAD_OF_HOUSEHOLD_CENTS,
}

# ---------------------------------------------------------------------------
# State allowance value — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "Each state allowance subtracts 400,000 cents from the
# annualized taxable wage (i.e., $4,000 per allowance)".
STATE_ALLOWANCE_VALUE_CENTS: int = 400_000


# ---------------------------------------------------------------------------
# Federal brackets (cents, basis points) — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The federal bracket table for SINGLE is four tiers:
# 10.00% on income from 0 up to 1,100,000 cents, 12.00% on income from
# 1,100,000 to 4,475,000 cents, 22.00% on income from 4,475,000 to
# 9,525,000 cents, and 24.00% on all income beyond 9,525,000 cents."
FED_BRACKETS_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 1_100_000, "rate_bps": 1000},
    {"lower_cents": 1_100_000, "upper_cents_or_null": 4_475_000, "rate_bps": 1200},
    {"lower_cents": 4_475_000, "upper_cents_or_null": 9_525_000, "rate_bps": 2200},
    {"lower_cents": 9_525_000, "upper_cents_or_null": None, "rate_bps": 2400},
]

# PRD §3.4: "For MARRIED_JOINT the breakpoints are 0 / 2,200,000 /
# 8,950,000 / 19,050,000 cents with the same four rates 10.00% /
# 12.00% / 22.00% / 24.00%."
FED_BRACKETS_MARRIED_JOINT = [
    {"lower_cents": 0, "upper_cents_or_null": 2_200_000, "rate_bps": 1000},
    {"lower_cents": 2_200_000, "upper_cents_or_null": 8_950_000, "rate_bps": 1200},
    {"lower_cents": 8_950_000, "upper_cents_or_null": 19_050_000, "rate_bps": 2200},
    {"lower_cents": 19_050_000, "upper_cents_or_null": None, "rate_bps": 2400},
]

# PRD §3.4: "For HEAD_OF_HOUSEHOLD the breakpoints are 0 / 1,575,000 /
# 6,005,000 / 9,525,000 cents with the same four rates."
FED_BRACKETS_HEAD_OF_HOUSEHOLD = [
    {"lower_cents": 0, "upper_cents_or_null": 1_575_000, "rate_bps": 1000},
    {"lower_cents": 1_575_000, "upper_cents_or_null": 6_005_000, "rate_bps": 1200},
    {"lower_cents": 6_005_000, "upper_cents_or_null": 9_525_000, "rate_bps": 2200},
    {"lower_cents": 9_525_000, "upper_cents_or_null": None, "rate_bps": 2400},
]


# ---------------------------------------------------------------------------
# State brackets — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "CA for SINGLE is three tiers: 2.00% on income from 0 up to
# 1,000,000 cents, 4.00% on income from 1,000,000 to 5,000,000 cents,
# and 6.00% on income above 5,000,000 cents."
STATE_BRACKETS_CA_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 1_000_000, "rate_bps": 200},
    {"lower_cents": 1_000_000, "upper_cents_or_null": 5_000_000, "rate_bps": 400},
    {"lower_cents": 5_000_000, "upper_cents_or_null": None, "rate_bps": 600},
]

# PRD §3.4: "NY for SINGLE is three tiers: 4.00% on income from 0 up to
# 1,200,000 cents, 6.00% on income from 1,200,000 to 8,000,000 cents,
# and 7.00% on income above 8,000,000 cents."
STATE_BRACKETS_NY_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 1_200_000, "rate_bps": 400},
    {"lower_cents": 1_200_000, "upper_cents_or_null": 8_000_000, "rate_bps": 600},
    {"lower_cents": 8_000_000, "upper_cents_or_null": None, "rate_bps": 700},
]

# PRD §3.4: "IL is a single-bracket flat rate of 4.95% on all income,
# applied regardless of filing status."
STATE_BRACKETS_IL_ANY = [
    {"lower_cents": 0, "upper_cents_or_null": None, "rate_bps": 495},
]

# PRD §3.4: "PA is a single-bracket flat rate of 3.07%, applied
# regardless of filing status."
STATE_BRACKETS_PA_ANY = [
    {"lower_cents": 0, "upper_cents_or_null": None, "rate_bps": 307},
]

# PRD §3.4: "TX is a single-bracket flat rate of 0% — i.e., Texas
# produces zero state withholding."
STATE_BRACKETS_TX_ANY = [
    {"lower_cents": 0, "upper_cents_or_null": None, "rate_bps": 0},
]

# ---------------------------------------------------------------------------
# Local flat rates — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "NYC is 3.80% of gross, PHL is 3.50% of gross."
LOCAL_FLAT_RATE_BPS_NYC: int = 380
LOCAL_FLAT_RATE_BPS_PHL: int = 350


# ---------------------------------------------------------------------------
# Social Security — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The Social Security tax is 6.20% applied to wages up to an
# annual wage base of 16,830,000 cents (i.e., $168,300)."
SS_WAGE_BASE_CENTS: int = 16_830_000
SS_RATE_BPS: int = 620


# ---------------------------------------------------------------------------
# Medicare — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "Standard Medicare withholding is 1.45% of the paycheck's
# gross, with no annual cap."
MEDICARE_BASE_RATE_BPS: int = 145

# PRD §3.4: "the employer must withhold an additional 0.90% on the
# portion of an employee's year-to-date Medicare wages that exceeds
# 20,000,000 cents (i.e., $200,000)".
ADDITIONAL_MEDICARE_THRESHOLD_CENTS: int = 20_000_000
ADDITIONAL_MEDICARE_RATE_BPS: int = 90


# ---------------------------------------------------------------------------
# Garnishment CCPA — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "The default cap is 25% of disposable income; however, if
# the employee has any ACTIVE CHILD_SUPPORT order, the cap rises to
# 50% of disposable income."
CCPA_BASE_PCT: int = 25
CCPA_CHILD_SUPPORT_PCT: int = 50

# PRD §3.5: order_type → priority_rank derivation.
# "CHILD_SUPPORT is rank 1, FEDERAL_TAX_LEVY is rank 2, STUDENT_LOAN is
# rank 3, and CREDITOR is rank 4. Lower ranks are paid first."
GARNISHMENT_PRIORITY: dict = {
    "CHILD_SUPPORT": 1,
    "FEDERAL_TAX_LEVY": 2,
    "STUDENT_LOAN": 3,
    "CREDITOR": 4,
}


# ---------------------------------------------------------------------------
# Supplemental flat rate for retro — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the retro adjustment itself is multiplied by the IRS
# supplemental flat rate of 22.00%".
SUPPLEMENTAL_FLAT_RATE_BPS: int = 2200


# ---------------------------------------------------------------------------
# Final-settlement window after termination — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a final-settlement paycheck may still be created for the
# employee provided the owning pay period's period_end is within seven
# days of the recorded termination_date".
FINAL_SETTLEMENT_WINDOW_DAYS: int = 7


# ---------------------------------------------------------------------------
# Payroll item hours bound — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "the sum of regular_hours, overtime_hours, and double_hours
# must not exceed 240 hours per period".
MAX_HOURS_PER_PERIOD: float = 240.0


# ---------------------------------------------------------------------------
# Garnishment cap percent bound — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "cap_pct_of_disposable (a per-pay-period cap expressed as
# an integer percent of disposable income in the range 1 through 100
# inclusive — values outside the range are rejected with
# ERR_INVALID_GARNISHMENT_CAP)".
GARNISHMENT_CAP_MIN: int = 1
GARNISHMENT_CAP_MAX: int = 100


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter specifies the maximum number of items
# to return, defaulting to 10, with a minimum of 1 and a maximum of
# 100. The offset parameter specifies the number of items to skip and
# defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Default 2024 tax year for seeded brackets
# ---------------------------------------------------------------------------
DEFAULT_TAX_YEAR: int = 2024


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PAY_PERIODS_PER_YEAR": PAY_PERIODS_PER_YEAR,
    "STANDARD_DEDUCTION_SINGLE_CENTS": STANDARD_DEDUCTION_SINGLE_CENTS,
    "SS_WAGE_BASE_CENTS": SS_WAGE_BASE_CENTS,
    "ADDITIONAL_MEDICARE_THRESHOLD_CENTS": (
        ADDITIONAL_MEDICARE_THRESHOLD_CENTS
    ),
    "DEFAULT_HOURLY_RATE_CENTS": 12_500,
    "DEFAULT_TAX_YEAR": DEFAULT_TAX_YEAR,
}


__all__ = [
    "PAY_PERIODS_PER_YEAR",
    "STANDARD_DEDUCTION_SINGLE_CENTS",
    "STANDARD_DEDUCTION_MARRIED_JOINT_CENTS",
    "STANDARD_DEDUCTION_HEAD_OF_HOUSEHOLD_CENTS",
    "STANDARD_DEDUCTION",
    "STATE_ALLOWANCE_VALUE_CENTS",
    "FED_BRACKETS_SINGLE",
    "FED_BRACKETS_MARRIED_JOINT",
    "FED_BRACKETS_HEAD_OF_HOUSEHOLD",
    "STATE_BRACKETS_CA_SINGLE",
    "STATE_BRACKETS_NY_SINGLE",
    "STATE_BRACKETS_IL_ANY",
    "STATE_BRACKETS_PA_ANY",
    "STATE_BRACKETS_TX_ANY",
    "LOCAL_FLAT_RATE_BPS_NYC",
    "LOCAL_FLAT_RATE_BPS_PHL",
    "SS_WAGE_BASE_CENTS",
    "SS_RATE_BPS",
    "MEDICARE_BASE_RATE_BPS",
    "ADDITIONAL_MEDICARE_THRESHOLD_CENTS",
    "ADDITIONAL_MEDICARE_RATE_BPS",
    "CCPA_BASE_PCT",
    "CCPA_CHILD_SUPPORT_PCT",
    "GARNISHMENT_PRIORITY",
    "SUPPLEMENTAL_FLAT_RATE_BPS",
    "FINAL_SETTLEMENT_WINDOW_DAYS",
    "MAX_HOURS_PER_PERIOD",
    "GARNISHMENT_CAP_MIN",
    "GARNISHMENT_CAP_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "DEFAULT_TAX_YEAR",
    "TEST_DEFAULTS",
]
