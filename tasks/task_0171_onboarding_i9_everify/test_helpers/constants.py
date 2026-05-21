"""Domain thresholds — numeric constants from PRD calculations.

PRD §2.6: "Several deadlines are measured in federal working days,
which the system defines as Monday through Friday, excluding U.S.
federal holidays cached in `SystemClock.federal_workdays_index`."
"""
from __future__ import annotations

from typing import FrozenSet


# ---------------------------------------------------------------------------
# Deadline windows — PRD §3.1 (Section 2 = 3 federal working days),
# PRD §3.5 (TNC contest = 10 federal working days, EVerify submit = 3
# federal working days), PRD §3.4 (STEM extension = 180 calendar days,
# document receipt = 90 calendar days).
# ---------------------------------------------------------------------------
SECTION2_WORKING_DAYS: int = 3
TNC_CONTEST_WORKING_DAYS: int = 10
EVERIFY_SUBMIT_WORKING_DAYS: int = 3
OPT_STEM_EXTENSION_DAYS: int = 180
DOCUMENT_RECEIPT_DAYS: int = 90
REHIRE_LOOKBACK_YEARS: int = 3


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field length / format constants — PRD §3.1
# ---------------------------------------------------------------------------
LEGAL_NAME_MIN_LEN: int = 1
LEGAL_NAME_MAX_LEN: int = 200
SSN_DIGITS: int = 9


# ---------------------------------------------------------------------------
# Federal holidays for 2026 / 2027 used by the difficulty-design recipes.
# PRD §2.6 names "U.S. federal holidays" as the exclusion set; the
# specific calendar is pinned by the scaffold's federal_workdays_index
# narrative for the test scenarios:
#     2026: Memorial Day May 25, Juneteenth Jun 19, Independence Day
#     observed Jul 3, Labor Day Sep 7, Columbus Day Oct 12, Veterans Day
#     Nov 11, Thanksgiving Nov 26, Christmas Dec 25.
#     2027: New Year Jan 1, MLK Day Jan 18.
# Used by test fixtures that need to anticipate the deadline arithmetic.
# ---------------------------------------------------------------------------
FEDERAL_HOLIDAYS_2026: FrozenSet[str] = frozenset({
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day (third Monday)
    "2026-02-16",  # Presidents Day (third Monday)
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day observed (Jul 4 is Saturday)
    "2026-09-07",  # Labor Day
    "2026-10-12",  # Columbus Day
    "2026-11-11",  # Veterans Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
})

FEDERAL_HOLIDAYS_2027: FrozenSet[str] = frozenset({
    "2027-01-01",  # New Year's Day
    "2027-01-18",  # MLK Day (third Monday)
})


# ---------------------------------------------------------------------------
# Test defaults — values used by factories when no override is given.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "EMPLOYEE_LEGAL_NAME": "Test Employee",
    "EMPLOYEE_DOB": "1990-01-15",
    "EMPLOYEE_START_DATE": "2026-06-01",
    "DOCUMENT_TITLE_PASSPORT": "U.S. Passport",
    "DOCUMENT_TITLE_DL": "Driver's License",
    "DOCUMENT_TITLE_SSN_CARD": "Social Security Card",
    "DOCUMENT_TITLE_EAD": "EAD I-766",
    "DOCUMENT_ISSUING_AUTHORITY_FED": "U.S. Department of State",
    "DOCUMENT_ISSUING_AUTHORITY_STATE": "California DMV",
    "DOCUMENT_ISSUING_AUTHORITY_USCIS": "USCIS",
    "DOCUMENT_NUMBER": "X12345678",
    "INITIAL_CLOCK_ISO": "2026-05-20T08:00:00.000Z",
}


__all__ = [
    "SECTION2_WORKING_DAYS",
    "TNC_CONTEST_WORKING_DAYS",
    "EVERIFY_SUBMIT_WORKING_DAYS",
    "OPT_STEM_EXTENSION_DAYS",
    "DOCUMENT_RECEIPT_DAYS",
    "REHIRE_LOOKBACK_YEARS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "LEGAL_NAME_MIN_LEN",
    "LEGAL_NAME_MAX_LEN",
    "SSN_DIGITS",
    "FEDERAL_HOLIDAYS_2026",
    "FEDERAL_HOLIDAYS_2027",
    "TEST_DEFAULTS",
]
