"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence (§3 narratives).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10, the minimum is 1, and the maximum
# is 100; the default offset is 0 and it must be zero or greater."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# PIA bend points — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "BEND_POINT_1 ... equals 117400 cents, that is $1,174 ...
# BEND_POINT_2 equals 707800 cents ($7,078)"
BEND_POINT_1: int = 117400
BEND_POINT_2: int = 707800

# PRD §3.5: "The 35-year capping table YEARLY_CAP_BY_YEAR sets $168,200 for
# 2024, the Social Security wage base"
YEARLY_CAP_BY_YEAR: dict = {
    2024: 16820000,
}

# PRD §3.1: "the per-year earnings threshold defined by
# QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR (which sets $1,730 per QC in 2024
# and $1,810 per QC in 2025)"
QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR: dict = {
    2024: 173000,
    2025: 181000,
}


# ---------------------------------------------------------------------------
# Family Maximum bend points — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "FMB_BP1 ... equals 150000 cents, that is $1,500 ...
# FMB_BP2 equals 216500 cents ($2,165) ...
# FMB_BP3 equals 282500 cents ($2,825)"
FMB_BP1: int = 150000
FMB_BP2: int = 216500
FMB_BP3: int = 282500

# PRD §3.5: "the Disability Insurance Benefit (DIB) special floor and
# ceiling clamp family_max_cents to be no less than 1.50 times pia_cents
# and no more than 1.85 times pia_cents."
DIB_FAMILY_MAX_FLOOR_RATIO: float = 1.50
DIB_FAMILY_MAX_CEILING_RATIO: float = 1.85


# ---------------------------------------------------------------------------
# SSI parameters — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the lesser of unearned income and GENERAL_INCOME_EXCLUSION
# (which is 2000 cents, that is $20)"
GENERAL_INCOME_EXCLUSION: int = 2000
# PRD §3.5: "added to EARNED_INCOME_EXCLUSION (which is 6500 cents, that
# is $65)"
EARNED_INCOME_EXCLUSION: int = 6500

# PRD §3.5: "FBR_BY_LIVING_ARRANGEMENT — 96700 cents ($967) for
# OWN_HOUSEHOLD, 64470 cents ($644.70, reduced by one-third) for
# ANOTHER_HOUSEHOLD, and 3000 cents ($30 personal-needs allowance) for
# INSTITUTION"
FBR_BY_LIVING_ARRANGEMENT: dict = {
    "OWN_HOUSEHOLD": 96700,
    "ANOTHER_HOUSEHOLD": 64470,
    "INSTITUTION": 3000,
}

# PRD §3.5: "requires countable_resources_cents to be at most
# SSI_RESOURCE_LIMIT_CENTS (which is 200000 cents, that is $2,000 for an
# individual)"
SSI_RESOURCE_LIMIT_CENTS: int = 200000


# ---------------------------------------------------------------------------
# Waiting period & back-pay — PRD §3.4, §3.5
# ---------------------------------------------------------------------------
# PRD §3.4: "the first day of the sixth full calendar month after the
# established onset. The constant that fixes this five-month interval
# is the statutory waiting period."
WAITING_PERIOD_MONTHS: int = 5

# PRD §3.5: "The cap MAX_PRE_FILING_RETRO_MONTHS is twelve."
MAX_PRE_FILING_RETRO_MONTHS: int = 12


# ---------------------------------------------------------------------------
# Diary cadence — PRD §3.4, §3.8
# ---------------------------------------------------------------------------
# PRD §3.4: "if medical_basis is MEETS_LISTING and the listing_code ...
# begins with '1.' or '11.', the diary is MIP and the diary interval is
# thirty-six months; if the medical basis is MEETS_LISTING but the listing
# code does not begin with '1.' or '11.', the diary is MINE and the
# interval is eighty-four months; if the medical basis is EQUALS_LISTING,
# the diary is MIE and the interval is eighteen months"
MIE_DIARY_MONTHS: int = 18
MIP_DIARY_MONTHS: int = 36
MINE_DIARY_MONTHS: int = 84


# ---------------------------------------------------------------------------
# Appeal window — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "the temporal precondition is that the current logical clock
# instant is on or before the last determination's created_at plus
# APPEAL_WINDOW_DAYS (which is sixty days)"
APPEAL_WINDOW_DAYS: int = 60


# ---------------------------------------------------------------------------
# CDR scheduling — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "requires that the clock be at or after review_due_date minus
# sixty days (otherwise ERR_CDR_NOT_DUE at 422)"
CDR_NOT_DUE_GRACE_DAYS: int = 60


# ---------------------------------------------------------------------------
# Hearing slot — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "end_at must equal start_at plus exactly sixty minutes."
HEARING_SLOT_MINUTES: int = 60


# ---------------------------------------------------------------------------
# Evidence — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "medical_findings — clinical free text of at least twenty
# characters"
MEDICAL_FINDINGS_MIN_LEN: int = 20
# PRD §3.3: "evidence_date that must be on or after the claimant's
# alleged_onset_date and on or before filing_date plus 730 days."
EVIDENCE_DATE_FILING_OFFSET_DAYS: int = 730


# ---------------------------------------------------------------------------
# Determination rationale — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "a free-text rationale of at least fifty characters"
RATIONALE_MIN_LEN: int = 50


# ---------------------------------------------------------------------------
# QC year range — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the calendar year (which must lie between 1978 and 2100
# inclusive)"
QC_YEAR_MIN: int = 1978
QC_YEAR_MAX: int = 2100


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "claimant_full_name": "Test Claimant",
    "ssn_last4": "1234",
    "rationale_text": (
        "This rationale exceeds the minimum length of fifty characters "
        "for adjudication purposes."
    ),
    "medical_findings_text": (
        "Clinical findings consistent with the alleged impairment."
    ),
    "hearing_office": "OHO_BOSTON",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "BEND_POINT_1",
    "BEND_POINT_2",
    "YEARLY_CAP_BY_YEAR",
    "QC_EARNINGS_THRESHOLD_CENTS_BY_YEAR",
    "FMB_BP1",
    "FMB_BP2",
    "FMB_BP3",
    "DIB_FAMILY_MAX_FLOOR_RATIO",
    "DIB_FAMILY_MAX_CEILING_RATIO",
    "GENERAL_INCOME_EXCLUSION",
    "EARNED_INCOME_EXCLUSION",
    "FBR_BY_LIVING_ARRANGEMENT",
    "SSI_RESOURCE_LIMIT_CENTS",
    "WAITING_PERIOD_MONTHS",
    "MAX_PRE_FILING_RETRO_MONTHS",
    "MIE_DIARY_MONTHS",
    "MIP_DIARY_MONTHS",
    "MINE_DIARY_MONTHS",
    "APPEAL_WINDOW_DAYS",
    "CDR_NOT_DUE_GRACE_DAYS",
    "HEARING_SLOT_MINUTES",
    "MEDICAL_FINDINGS_MIN_LEN",
    "EVIDENCE_DATE_FILING_OFFSET_DAYS",
    "RATIONALE_MIN_LEN",
    "QC_YEAR_MIN",
    "QC_YEAR_MAX",
    "TEST_DEFAULTS",
]
