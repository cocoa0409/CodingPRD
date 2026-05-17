"""Payroll constants — federal/state/local rates, thresholds, and brackets."""

PAY_PERIODS_PER_YEAR = 26

# Federal standard deduction (cents)
STANDARD_DEDUCTION_CENTS = {
    "SINGLE": 1_390_000,
    "MARRIED_JOINT": 2_780_000,
    "HEAD_OF_HOUSEHOLD": 2_090_000,
}

# Federal brackets per scaffold §1.3:
# {lo, hi (None=unbounded), rate_bps}
FED_BRACKETS = {
    "SINGLE": [
        {"lo": 0, "hi": 1_100_000, "rate_bps": 1000},
        {"lo": 1_100_000, "hi": 4_475_000, "rate_bps": 1200},
        {"lo": 4_475_000, "hi": 9_525_000, "rate_bps": 2200},
        {"lo": 9_525_000, "hi": None, "rate_bps": 2400},
    ],
    "MARRIED_JOINT": [
        {"lo": 0, "hi": 2_200_000, "rate_bps": 1000},
        {"lo": 2_200_000, "hi": 8_950_000, "rate_bps": 1200},
        {"lo": 8_950_000, "hi": 19_050_000, "rate_bps": 2200},
        {"lo": 19_050_000, "hi": None, "rate_bps": 2400},
    ],
    "HEAD_OF_HOUSEHOLD": [
        {"lo": 0, "hi": 1_575_000, "rate_bps": 1000},
        {"lo": 1_575_000, "hi": 6_005_000, "rate_bps": 2200 - 1000},  # 12%
        {"lo": 6_005_000, "hi": 9_525_000, "rate_bps": 2200},
        {"lo": 9_525_000, "hi": None, "rate_bps": 2400},
    ],
}

# Correct HEAD_OF_HOUSEHOLD per PRD:
# 10% on [0, 1_575_000), 12% on [1_575_000, 6_005_000), 22% on [6_005_000, 9_525_000), 24% on [9_525_000, +inf)
FED_BRACKETS["HEAD_OF_HOUSEHOLD"] = [
    {"lo": 0, "hi": 1_575_000, "rate_bps": 1000},
    {"lo": 1_575_000, "hi": 6_005_000, "rate_bps": 1200},
    {"lo": 6_005_000, "hi": 9_525_000, "rate_bps": 2200},
    {"lo": 9_525_000, "hi": None, "rate_bps": 2400},
]

# State bracket lookup — for each (state, filing_status) returns ordered list of brackets.
# IL, PA, TX apply regardless of filing status (use "ANY" key in scaffold).
# NY/CA per scaffold provide SINGLE only; we mirror for other statuses (best effort);
# PRD does not specify other statuses for NY/CA so we apply the SINGLE table as a
# reasonable default.
STATE_BRACKETS = {
    "CA": {
        "SINGLE": [
            {"lo": 0, "hi": 1_000_000, "rate_bps": 200},
            {"lo": 1_000_000, "hi": 5_000_000, "rate_bps": 400},
            {"lo": 5_000_000, "hi": None, "rate_bps": 600},
        ],
        "MARRIED_JOINT": [
            {"lo": 0, "hi": 1_000_000, "rate_bps": 200},
            {"lo": 1_000_000, "hi": 5_000_000, "rate_bps": 400},
            {"lo": 5_000_000, "hi": None, "rate_bps": 600},
        ],
        "HEAD_OF_HOUSEHOLD": [
            {"lo": 0, "hi": 1_000_000, "rate_bps": 200},
            {"lo": 1_000_000, "hi": 5_000_000, "rate_bps": 400},
            {"lo": 5_000_000, "hi": None, "rate_bps": 600},
        ],
    },
    "NY": {
        "SINGLE": [
            {"lo": 0, "hi": 1_200_000, "rate_bps": 400},
            {"lo": 1_200_000, "hi": 8_000_000, "rate_bps": 600},
            {"lo": 8_000_000, "hi": None, "rate_bps": 700},
        ],
        "MARRIED_JOINT": [
            {"lo": 0, "hi": 1_200_000, "rate_bps": 400},
            {"lo": 1_200_000, "hi": 8_000_000, "rate_bps": 600},
            {"lo": 8_000_000, "hi": None, "rate_bps": 700},
        ],
        "HEAD_OF_HOUSEHOLD": [
            {"lo": 0, "hi": 1_200_000, "rate_bps": 400},
            {"lo": 1_200_000, "hi": 8_000_000, "rate_bps": 600},
            {"lo": 8_000_000, "hi": None, "rate_bps": 700},
        ],
    },
    "IL": {
        "ANY": [{"lo": 0, "hi": None, "rate_bps": 495}],
    },
    "PA": {
        "ANY": [{"lo": 0, "hi": None, "rate_bps": 307}],
    },
    "TX": {
        "ANY": [{"lo": 0, "hi": None, "rate_bps": 0}],
    },
}

# State standard deduction (illustrative — keep simple; per scaffold not enumerated, use 0)
STATE_STANDARD_DEDUCTION_CENTS = 0

# Each state allowance reduces annualized taxable wage by this amount
STATE_ALLOWANCE_VALUE_CENTS = 400_000

# Local flat rates (basis points) — per scaffold
LOCAL_FLAT_RATE_BPS = {
    "NYC": 380,   # 3.80%
    "PHL": 350,   # 3.50%
    "NONE": 0,
}

# FICA Social Security
SS_WAGE_BASE_CENTS = 16_830_000
SS_RATE_BPS = 620

# Medicare
MEDICARE_BASE_RATE_BPS = 145
ADDITIONAL_MEDICARE_THRESHOLD_CENTS = 20_000_000
ADDITIONAL_MEDICARE_RATE_BPS = 90

# Supplemental flat rate for retro (federal — 22%)
SUPPLEMENTAL_FED_RATE_BPS = 2200

# Garnishment CCPA
CCPA_BASE_PCT = 25
CCPA_CHILD_SUPPORT_PCT = 50

# Garnishment priority
GARNISHMENT_PRIORITY = {
    "CHILD_SUPPORT": 1,
    "FEDERAL_TAX_LEVY": 2,
    "STUDENT_LOAN": 3,
    "CREDITOR": 4,
}

# Hours sanity
MAX_HOURS_PER_PERIOD = 240

# Final-settlement window (days post-termination)
FINAL_SETTLEMENT_WINDOW_DAYS = 7
