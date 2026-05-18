"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Receipt number format — PRD §2.7
# ---------------------------------------------------------------------------
# PRD §2.7: "Receipt Numbers are exactly 13 characters long".
# PRD §2.7: "Three-letter prefix, two-digit year, three-digit
# day-of-fiscal-year, and five-digit sequence sum to thirteen
# characters."
RECEIPT_NUMBER_LENGTH: int = 13
RECEIPT_PREFIX_LENGTH: int = 3
RECEIPT_YEAR_LENGTH: int = 2
RECEIPT_DOY_LENGTH: int = 3
RECEIPT_SEQ_LENGTH: int = 5

# PRD §2.7: "The valid receipt_prefix values are MSC, EAC, WAC, NBC,
# LIN, SRC, IOE, and YSC."
RECEIPT_PREFIXES = ["MSC", "EAC", "WAC", "NBC", "LIN", "SRC", "IOE", "YSC"]

# PRD §2.7 / §3.3: fiscal year starts on October 1.
FISCAL_YEAR_START_MONTH: int = 10


# ---------------------------------------------------------------------------
# Biometrics / Interview lead-time and reschedule windows — PRD §3.4 / §3.6
# ---------------------------------------------------------------------------
# PRD §3.4: "The scheduled_at value must be at least seven days from
# the present moment; an earlier value is rejected with
# ERR_BIOMETRICS_TOO_SOON."
BIOMETRICS_LEAD_DAYS: int = 7

# PRD §3.4: "the request must arrive no later than 24 hours before the
# existing appointment's scheduled_at".
BIOMETRICS_RESCHEDULE_CUTOFF_HOURS: int = 24

# PRD §3.4: "the current reschedule_count on the chain must be strictly
# less than 3, so the fourth reschedule attempt on the same chain is
# rejected with ERR_BIOMETRICS_RESCHEDULE_LIMIT."
BIOMETRICS_MAX_RESCHEDULES: int = 3

# PRD §3.4: "Marking the appointment as NO_SHOW requires that the
# current time be more than 24 hours past the scheduled time".
# PRD §3.6: "Marking an interview as NO_SHOW requires that the current
# time be more than 24 hours past the scheduled time".
NO_SHOW_GRACE_HOURS: int = 24

# PRD §3.6: "The scheduled_at must be at least 14 days into the future,
# or the request is rejected with ERR_INTERVIEW_TOO_SOON."
INTERVIEW_LEAD_DAYS: int = 14


# ---------------------------------------------------------------------------
# RFE response window — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "Its deadline_at is set to issued_at plus the matching
# CaseTypeConfig.rfe_response_window_days converted to seconds (each
# day is 86,400 seconds; the default window across all four form types
# is 87 days)."
DEFAULT_RFE_WINDOW_DAYS: int = 87
SECONDS_PER_DAY: int = 86400


# ---------------------------------------------------------------------------
# Case completeness score — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "The weights are fixed at 0.40 for status, 0.20 for
# biometrics, 0.10 for RFE, 0.15 for interview, and 0.15 for priority
# — summing to 1.00."
WEIGHT_STATUS: float = 0.40
WEIGHT_BIOMETRICS: float = 0.20
WEIGHT_RFE: float = 0.10
WEIGHT_INTERVIEW: float = 0.15
WEIGHT_PRIORITY: float = 0.15

# PRD §3.11: "the result is clamped into the inclusive 0-to-100 integer
# range".
SCORE_FLOOR: int = 0
SCORE_CEILING: int = 100

# PRD §3.11: f_status table.
STATUS_RAW = {
    "DRAFT": 0.00,
    "FILED": 0.10,
    "BIOMETRICS_SCHEDULED": 0.20,
    "BIOMETRICS_COMPLETED": 0.40,
    "RFE_ISSUED": 0.30,
    "RFE_RESPONDED": 0.50,
    "INTERVIEW_SCHEDULED": 0.70,
    "READY_FOR_DECISION": 0.90,
    "APPROVED": 1.00,
    "DENIED": 1.00,
    "WITHDRAWN": 1.00,
}


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10, the minimum is 1, and the maximum
# is 100. The default offset is 0 and the minimum is 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Field length / format bounds — PRD §3.1 / §3.4 / §3.5 / §3.6
# ---------------------------------------------------------------------------
# PRD §3.1: "full_name between 1 and 120 characters".
FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 120

# PRD §3.5: "officer_notes between 1 and 2000 characters".
OFFICER_NOTES_MIN_LEN: int = 1
OFFICER_NOTES_MAX_LEN: int = 2000

# PRD §3.4: "location_code as a 4-to-6-character uppercase alphanumeric
# Application Support Center identifier".
LOCATION_CODE_MIN_LEN: int = 4
LOCATION_CODE_MAX_LEN: int = 6

# PRD §3.6: "field_office_code of 3-to-5 uppercase letters".
FIELD_OFFICE_CODE_MIN_LEN: int = 3
FIELD_OFFICE_CODE_MAX_LEN: int = 5


# ---------------------------------------------------------------------------
# Enumeration sets (declared verbatim in PRD §3 / §1.1)
# ---------------------------------------------------------------------------
CASE_TYPES = ["I-130", "I-485", "I-765", "I-131"]
PREFERENCE_CATEGORIES = ["F1", "F2A", "F2B", "F3", "F4", "IR"]
PREFERENCE_CATEGORIES_BULLETIN = ["F1", "F2A", "F2B", "F3", "F4"]
RELATIONSHIPS = ["SPOUSE", "CHILD", "PARENT", "SIBLING", "FIANCE"]
RFE_REASON_CODES = [
    "MISSING_DOC", "IDENTITY_DOC", "FINANCIAL_PROOF",
    "MEDICAL_EXAM", "TRANSLATION",
]
INTERVIEW_OUTCOMES = [
    "RECOMMEND_APPROVAL", "RECOMMEND_DENIAL", "CONTINUED",
]
OFFICER_DENIAL_REASONS = ["OFFICER_DENIAL", "INELIGIBLE"]
CHART_TYPES = ["FINAL_ACTION", "DATES_FOR_FILING"]

CASE_STATUSES = [
    "DRAFT", "FILED", "BIOMETRICS_SCHEDULED", "BIOMETRICS_COMPLETED",
    "RFE_ISSUED", "RFE_RESPONDED", "INTERVIEW_SCHEDULED",
    "READY_FOR_DECISION", "APPROVED", "DENIED", "WITHDRAWN",
]
PRIORITY_DATE_STATUSES = [
    "NOT_APPLICABLE", "CURRENT", "NOT_CURRENT", "RETROGRESSED",
]


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values for reuse.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "FULL_NAME": "Test Person",
    "EMAIL": "test@example.com",
    "DATE_OF_BIRTH": "1990-01-01",
    "COUNTRY_OF_CITIZENSHIP": "MEX",
    "COUNTRY_OF_CHARGEABILITY": "MEX",
    "PREFERENCE_CATEGORY_DEFAULT": "F2A",
    "RELATIONSHIP_DEFAULT": "SPOUSE",
    "LOCATION_CODE": "ASC01",
    "FIELD_OFFICE_CODE": "NYC",
    "OFFICER_NOTES": "Please submit additional documentation.",
    "RECEIPT_PREFIX_DEFAULT": "MSC",
}


__all__ = [
    "RECEIPT_NUMBER_LENGTH",
    "RECEIPT_PREFIX_LENGTH",
    "RECEIPT_YEAR_LENGTH",
    "RECEIPT_DOY_LENGTH",
    "RECEIPT_SEQ_LENGTH",
    "RECEIPT_PREFIXES",
    "FISCAL_YEAR_START_MONTH",
    "BIOMETRICS_LEAD_DAYS",
    "BIOMETRICS_RESCHEDULE_CUTOFF_HOURS",
    "BIOMETRICS_MAX_RESCHEDULES",
    "NO_SHOW_GRACE_HOURS",
    "INTERVIEW_LEAD_DAYS",
    "DEFAULT_RFE_WINDOW_DAYS",
    "SECONDS_PER_DAY",
    "WEIGHT_STATUS",
    "WEIGHT_BIOMETRICS",
    "WEIGHT_RFE",
    "WEIGHT_INTERVIEW",
    "WEIGHT_PRIORITY",
    "SCORE_FLOOR",
    "SCORE_CEILING",
    "STATUS_RAW",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "OFFICER_NOTES_MIN_LEN",
    "OFFICER_NOTES_MAX_LEN",
    "LOCATION_CODE_MIN_LEN",
    "LOCATION_CODE_MAX_LEN",
    "FIELD_OFFICE_CODE_MIN_LEN",
    "FIELD_OFFICE_CODE_MAX_LEN",
    "CASE_TYPES",
    "PREFERENCE_CATEGORIES",
    "PREFERENCE_CATEGORIES_BULLETIN",
    "RELATIONSHIPS",
    "RFE_REASON_CODES",
    "INTERVIEW_OUTCOMES",
    "OFFICER_DENIAL_REASONS",
    "CHART_TYPES",
    "CASE_STATUSES",
    "PRIORITY_DATE_STATUSES",
    "TEST_DEFAULTS",
]
