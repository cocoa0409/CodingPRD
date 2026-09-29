"""Numeric constants published by the API contract.

Money is integer cents throughout; percentages are decimals with two places.
"""

# --- Logical clock ----------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination -------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- Eligibility budgeting --------------------------------------------------
EARNED_INCOME_DISREGARD_CENTS = 12000
CHILD_SUPPORT_PASSTHROUGH_CENTS = 5000
RESOURCE_LIMIT_CENTS = 200000

# --- Grant computation ------------------------------------------------------
PAYMENT_STANDARD_CENTS = {
    1: 26000,
    2: 39000,
    3: 49000,
    4: 59000,
    5: 68000,
    6: 76000,
}
PAYMENT_STANDARD_INCREMENT_CENTS = 7000
RATABLE_REDUCTION_FACTOR = 0.85
MAXIMUM_GRANT_CENTS = 90000
MINIMUM_ISSUANCE_CENTS = 1000


def payment_standard_cents(household_size: int) -> int:
    """Payment standard for a household size, extended beyond six people."""
    if household_size <= 6:
        return PAYMENT_STANDARD_CENTS[household_size]
    return PAYMENT_STANDARD_CENTS[6] + PAYMENT_STANDARD_INCREMENT_CENTS * (
        household_size - 6
    )


# --- Family-type derivation -------------------------------------------------
YOUNGEST_CHILD_UNDER_SIX_MONTHS = 72

# --- Diversion --------------------------------------------------------------
DIVERSION_LUMP_SUM_MULTIPLIER = 3
DIVERSION_LUMP_SUM_CAP_CENTS = 200000
DIVERSION_MAX_INELIGIBILITY_MONTHS = 12

# --- Time limits ------------------------------------------------------------
STATE_TIME_LIMIT_MONTHS = 24
FEDERAL_TIME_LIMIT_MONTHS = 60
EXTENSION_LIFETIME_MONTHS = 12
MIN_EXTENSION_MONTHS_REQUESTED = 1
MAX_EXTENSION_MONTHS_REQUESTED = 12

# --- Work assignments -------------------------------------------------------
MIN_SCHEDULED_WEEKLY_HOURS = 1
MAX_SCHEDULED_WEEKLY_HOURS = 60
WEEKLY_TO_MONTHLY_HOURS_FACTOR = 4

CORE_ACTIVITY_CATEGORIES = (
    "UNSUBSIDIZED_EMPLOYMENT",
    "SUBSIDIZED_EMPLOYMENT",
    "WORK_EXPERIENCE",
    "ON_THE_JOB_TRAINING",
    "JOB_SEARCH_READINESS",
    "COMMUNITY_SERVICE",
    "VOCATIONAL_EDUCATION",
)
NON_CORE_ACTIVITY_CATEGORIES = (
    "JOB_SKILLS_TRAINING_DIRECT",
    "EDUCATION_RELATED_TO_EMPLOYMENT",
    "SECONDARY_SCHOOL",
)

# Weekly hour requirements keyed by the case's frozen family type.
REQUIRED_WEEKLY_HOURS = {
    "CHILD_ONLY": 0,
    "SINGLE_PARENT_CHILD_UNDER_6": 20,
    "SINGLE_PARENT": 30,
    "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE": 35,
    "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE": 55,
}
REQUIRED_CORE_WEEKLY_HOURS = {
    "CHILD_ONLY": 0,
    "SINGLE_PARENT_CHILD_UNDER_6": 20,
    "SINGLE_PARENT": 20,
    "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE": 30,
    "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE": 50,
}
REQUIRED_MONTHLY_HOURS = {
    key: value * WEEKLY_TO_MONTHLY_HOURS_FACTOR
    for key, value in REQUIRED_WEEKLY_HOURS.items()
}
REQUIRED_CORE_MONTHLY_HOURS = {
    key: value * WEEKLY_TO_MONTHLY_HOURS_FACTOR
    for key, value in REQUIRED_CORE_WEEKLY_HOURS.items()
}

# --- Participation reporting ------------------------------------------------
MIN_REPORTED_HOURS = 0
MAX_REPORTED_HOURS = 744
SELF_REPORT_CREDIT_NUMERATOR = 1
SELF_REPORT_CREDIT_DENOMINATOR = 2

# --- Compliance and sanctions ----------------------------------------------
CONCILIATION_DEADLINE_DAYS = 30
MAX_SANCTION_LEVEL = 3
SANCTION_PCT_BY_LEVEL = {0: 0.00, 1: 0.25, 2: 0.50, 3: 1.00}

# --- Supportive services ----------------------------------------------------
SERVICE_TYPE_FY_CAP_CENTS = {
    "TRANSPORTATION": 60000,
    "CHILD_CARE": 240000,
    "WORK_EXPENSE": 30000,
}
CASE_FY_SUPPORTIVE_CAP_CENTS = 300000

# --- Overpayments -----------------------------------------------------------
RECOUPMENT_PCT_BY_CLAIM_TYPE = {
    "AGENCY_ERROR": 0.05,
    "CLIENT_ERROR": 0.10,
    "SUSPECTED_FRAUD": 0.20,
}
SUBSTANTIATED_FRAUD_RECOUPMENT_PCT = 0.25
MINIMUM_MONTHLY_RECOUPMENT_CENTS = 1000

# --- Federal reporting ------------------------------------------------------
MIN_QUARTER = 1
MAX_QUARTER = 4
MONTHS_PER_QUARTER = 3
STATUTORY_ALL_FAMILIES_TARGET_PCT = 50.00
STATUTORY_TWO_PARENT_TARGET_PCT = 90.00
MAX_CASELOAD_REDUCTION_CREDIT_PCT = 50.00
SANCTION_DISREGARD_MONTHS_PER_CASE_PER_FY = 3

# Fiscal-year quarter to calendar month mapping; Q1 sits in the prior calendar
# year because the fiscal year opens in October.
QUARTER_MONTH_OFFSETS = {
    1: [(-1, 10), (-1, 11), (-1, 12)],
    2: [(0, 1), (0, 2), (0, 3)],
    3: [(0, 4), (0, 5), (0, 6)],
    4: [(0, 7), (0, 8), (0, 9)],
}


def quarter_months(fiscal_year: int, quarter: int):
    """The three ``YYYY-MM`` months covered by a fiscal-year quarter."""
    return [
        "%04d-%02d" % (fiscal_year + year_delta, month)
        for year_delta, month in QUARTER_MONTH_OFFSETS[quarter]
    ]


def fiscal_year_for_month(month: str) -> int:
    """Fiscal year owning a ``YYYY-MM`` month; October onward rolls forward."""
    year, month_number = int(month[:4]), int(month[5:7])
    return year + 1 if month_number >= 10 else year
