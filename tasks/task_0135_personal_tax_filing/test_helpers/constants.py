"""Domain thresholds — numeric constants from PRD calculations and §5.

All monetary values are in integer cents per PRD §2.5.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Tax-year range — PRD §3.1
# ---------------------------------------------------------------------------
TAX_YEAR_MIN: int = 2020
TAX_YEAR_MAX: int = 2025
DEFAULT_TAX_YEAR: int = 2025


# ---------------------------------------------------------------------------
# Self-employment tax — PRD §3.5 step 1
# ---------------------------------------------------------------------------
SE_NET_FACTOR_BPS: int = 9235      # 92.35%
SE_RATE_BPS: int = 1530            # 15.30%
CAP_LOSS_FLOOR_CENTS: int = -300_000  # PRD §3.5: capital-loss floored at -300000 cents


# ---------------------------------------------------------------------------
# Standard deduction lookup — PRD §3.5 step 2
# ---------------------------------------------------------------------------
STANDARD_DEDUCTION: dict = {
    "SINGLE": 1_500_000,
    "MARRIED_JOINT": 3_000_000,
    "MARRIED_SEPARATE": 1_500_000,
    "HEAD_OF_HOUSEHOLD": 2_225_000,
    "QUALIFYING_SURVIVING_SPOUSE": 3_000_000,
}
BLIND_ADDON_CENTS: int = 150_000

# ---------------------------------------------------------------------------
# Itemized deduction — PRD §3.5 step 2
# ---------------------------------------------------------------------------
MEDICAL_FLOOR_BPS: int = 750    # 7.5% in tenth-percent: 7.5/100 = 75/1000 per PRD formula
SALT_CAP_CENTS: int = 1_000_000
CHARITY_CAP_PCT: int = 60


# ---------------------------------------------------------------------------
# Regular tax brackets — PRD §3.5 step 3
# ---------------------------------------------------------------------------
BRACKETS_SINGLE: list = [
    (0,         1_100_000,  1000),   # 10% up to $11,000
    (1_100_000, 4_475_000,  1200),   # 12%
    (4_475_000, 9_537_500,  2200),   # 22%
    (9_537_500, 18_222_500, 2400),   # 24%
    (18_222_500, float("inf"), 3200), # 32%
]
BRACKETS_MARRIED_JOINT: list = [
    (0,          2_200_000,  1000),
    (2_200_000,  8_950_000,  1200),
    (8_950_000, 19_075_000,  2200),
    (19_075_000, float("inf"), 2400),
]


# ---------------------------------------------------------------------------
# AMT — PRD §3.5 step 4
# ---------------------------------------------------------------------------
AMT_EXEMPTION: dict = {
    "SINGLE": 8_550_000,
    "MARRIED_JOINT": 13_325_000,
    "MARRIED_SEPARATE": 6_662_500,
    "HEAD_OF_HOUSEHOLD": 8_550_000,
    "QUALIFYING_SURVIVING_SPOUSE": 13_325_000,
}
AMT_LOW_RATE_BPS: int = 2600
AMT_HIGH_RATE_BPS: int = 2800
AMT_BRACKET_BREAK_CENTS: int = 23_222_500


# ---------------------------------------------------------------------------
# CTC — PRD §3.6
# ---------------------------------------------------------------------------
CTC_BASE_PER_CHILD_CENTS: int = 200_000
CTC_REFUNDABLE_CAP_PER_CHILD_CENTS: int = 170_000
CTC_PHASEOUT_START: dict = {
    "SINGLE": 20_000_000,
    "MARRIED_JOINT": 40_000_000,
    "MARRIED_SEPARATE": 20_000_000,
    "HEAD_OF_HOUSEHOLD": 20_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 40_000_000,
}
CTC_PHASEOUT_STEP_CENTS: int = 100_000
CTC_PHASEOUT_RATE_BPS: int = 500


# ---------------------------------------------------------------------------
# AOTC — PRD §3.6
# ---------------------------------------------------------------------------
AOTC_PER_STUDENT_CAP_CENTS: int = 400_000
AOTC_FIRST_TIER_CENTS: int = 200_000
AOTC_SECOND_TIER_RATE_BPS: int = 2500
AOTC_REFUNDABLE_PCT: int = 40
AOTC_PHASEOUT_START: dict = {
    "SINGLE": 8_000_000,
    "MARRIED_JOINT": 16_000_000,
    "MARRIED_SEPARATE": 0,
    "HEAD_OF_HOUSEHOLD": 8_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 16_000_000,
}
AOTC_PHASEOUT_RANGE: dict = {
    "SINGLE": 1_000_000,
    "MARRIED_JOINT": 2_000_000,
    "MARRIED_SEPARATE": 0,
    "HEAD_OF_HOUSEHOLD": 1_000_000,
    "QUALIFYING_SURVIVING_SPOUSE": 2_000_000,
}


# ---------------------------------------------------------------------------
# EITC — PRD §3.6
# ---------------------------------------------------------------------------
EITC_MAX: dict = {0: 60_000, 1: 400_000, 2: 660_000, 3: 740_000}
EITC_PHASEOUT_START: dict = {
    0: 1_000_000, 1: 2_200_000, 2: 2_200_000, 3: 2_200_000,
}
EITC_PHASEOUT_END: dict = {
    0: 1_882_000, 1: 4_949_000, 2: 5_535_000, 3: 5_907_000,
}


# ---------------------------------------------------------------------------
# Safe harbor — PRD §3.10
# ---------------------------------------------------------------------------
SAFE_HARBOR_CURRENT_PCT: int = 90
HIGH_INCOME_PRIOR_PCT: int = 110
LOW_INCOME_PRIOR_PCT: int = 100
HIGH_INCOME_THRESHOLD_CENTS: int = 15_000_000


# ---------------------------------------------------------------------------
# Loose sanity caps — PRD §3.2
# ---------------------------------------------------------------------------
INCOME_DOC_LOOSE_CAP_CENTS: int = 100_000_000  # cost_basis_cents - proceeds_cents ceiling


# ---------------------------------------------------------------------------
# Defaults for tests — payload factory convenience
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "TAX_YEAR": DEFAULT_TAX_YEAR,
    "FILING_STATUS": "SINGLE",
    "DEDUCTION_METHOD": "STANDARD",
    "DEPENDENTS_COUNT": 0,
    "QUALIFYING_CHILDREN": 0,
    "PAYER_EIN": "12-3456789",
    "PAYER_NAME": "Acme Corp",
    "FULL_NAME": "Pat Q. Taxpayer",
    "DATE_OF_BIRTH": "1985-04-01",
    "SSN_LAST4": "1234",
    "STREET": "123 Main St",
    "CITY": "Albany",
    "STATE": "NY",
    "ZIP": "12207",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TAX_YEAR_MIN",
    "TAX_YEAR_MAX",
    "DEFAULT_TAX_YEAR",
    "SE_NET_FACTOR_BPS",
    "SE_RATE_BPS",
    "CAP_LOSS_FLOOR_CENTS",
    "STANDARD_DEDUCTION",
    "BLIND_ADDON_CENTS",
    "MEDICAL_FLOOR_BPS",
    "SALT_CAP_CENTS",
    "CHARITY_CAP_PCT",
    "BRACKETS_SINGLE",
    "BRACKETS_MARRIED_JOINT",
    "AMT_EXEMPTION",
    "AMT_LOW_RATE_BPS",
    "AMT_HIGH_RATE_BPS",
    "AMT_BRACKET_BREAK_CENTS",
    "CTC_BASE_PER_CHILD_CENTS",
    "CTC_REFUNDABLE_CAP_PER_CHILD_CENTS",
    "CTC_PHASEOUT_START",
    "CTC_PHASEOUT_STEP_CENTS",
    "CTC_PHASEOUT_RATE_BPS",
    "AOTC_PER_STUDENT_CAP_CENTS",
    "AOTC_FIRST_TIER_CENTS",
    "AOTC_SECOND_TIER_RATE_BPS",
    "AOTC_REFUNDABLE_PCT",
    "AOTC_PHASEOUT_START",
    "AOTC_PHASEOUT_RANGE",
    "EITC_MAX",
    "EITC_PHASEOUT_START",
    "EITC_PHASEOUT_END",
    "SAFE_HARBOR_CURRENT_PCT",
    "HIGH_INCOME_PRIOR_PCT",
    "LOW_INCOME_PRIOR_PCT",
    "HIGH_INCOME_THRESHOLD_CENTS",
    "INCOME_DOC_LOOSE_CAP_CENTS",
    "TEST_DEFAULTS",
]
